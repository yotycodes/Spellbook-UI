#!/usr/bin/env python3
"""posekit — build dynamic COCO-18 OpenPose skeletons from anatomy rules (head-count proportions,
ribcage/pelvis twist, contrapposto, foreshortening) instead of hand-placing pixels.

Run with any python that has Pillow (e.g. ~/stable-diffusion-webui-forge/venv/bin/python).

  python posekit.py list                                   # list presets
  python posekit.py render flying_punch --heads 3.5 --out pose.png [--w 832 --h 1216] [--size 0.62] [--at 0.5 0.55] [--mirror]
  python posekit.py sheet --heads 3.5 --out sheet.png      # preview every preset

Angles are COMPASS degrees in image space: 0 = up, 90 = image-right, 180 = down, 270 = image-left.
Yaw: 0 = facing camera, +90 = profile facing image-right, -90 = facing image-left, 180 = back to camera.
Subject's RIGHT side is on image LEFT when facing camera (OpenPose convention).
Keypoints: 0 nose 1 neck 2 RSho 3 RElb 4 RWri 5 LSho 6 LElb 7 LWri 8 RHip 9 RKnee 10 RAnk
           11 LHip 12 LKnee 13 LAnk 14 REye 15 LEye 16 REar 17 LEar
"""
import math, sys, argparse
from PIL import Image, ImageDraw

LIMBS = [(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),(1,11),(11,12),(12,13),(1,0),(0,14),(14,16),(0,15),(15,17)]
COLORS = [(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),(85,255,0),(0,255,0),(0,255,85),(0,255,170),
          (0,255,255),(0,170,255),(0,85,255),(0,0,255),(85,0,255),(170,0,255),(255,0,255),(255,0,170),(255,0,85)]

# Segment lengths in HEAD units, keyed by head-count (book ch.1/7: 3 heads = age 3-5/chibi, 4 = 6-8, 5 = 8-12, 7.5 adult).
# Children: big head, short legs (leg:torso ~ 1:1); adults: legs ~ half the height.
PROP = {
    2.5: dict(ntn=0.45, torso=0.75, sho=0.45, hip=0.28, uarm=0.40, farm=0.38, thigh=0.50, shin=0.45, eye=0.20, eyeup=0.10, ear=0.42),
    3.5: dict(ntn=0.55, torso=1.05, sho=0.55, hip=0.32, uarm=0.55, farm=0.50, thigh=0.75, shin=0.70, eye=0.19, eyeup=0.11, ear=0.42),
    5.0: dict(ntn=0.62, torso=1.55, sho=0.72, hip=0.42, uarm=0.85, farm=0.75, thigh=1.15, shin=1.10, eye=0.19, eyeup=0.10, ear=0.44),
    6.5: dict(ntn=0.70, torso=2.15, sho=0.92, hip=0.55, uarm=1.25, farm=1.05, thigh=1.60, shin=1.55, eye=0.19, eyeup=0.10, ear=0.45),
    7.5: dict(ntn=0.75, torso=2.45, sho=1.00, hip=0.60, uarm=1.45, farm=1.25, thigh=1.90, shin=1.85, eye=0.19, eyeup=0.10, ear=0.45),
    8.5: dict(ntn=0.78, torso=2.70, sho=1.05, hip=0.62, uarm=1.60, farm=1.40, thigh=2.20, shin=2.15, eye=0.19, eyeup=0.10, ear=0.45),
}
def props(n):
    ks = sorted(PROP)
    n = max(ks[0], min(ks[-1], n))
    for a, b in zip(ks, ks[1:]):
        if a <= n <= b:
            t = (n - a) / (b - a)
            return {k: PROP[a][k] * (1 - t) + PROP[b][k] * t for k in PROP[a]}

def d(a):  # compass degrees -> unit vector in image coords (y down)
    r = math.radians(a); return (math.sin(r), -math.cos(r))
def add(p, v, s=1.0): return (p[0] + v[0] * s, p[1] + v[1] * s)
def ik(root, target, a, b, bend):
    """Two-bone IK in the image plane. bend=+1 bends the joint clockwise of root->target, -1 counter-clockwise.
    Returns (joint, end); end is clamped to reach if the target is too far."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    dist = max(1e-6, min(math.hypot(dx, dy), a + b - 1e-4, ))
    dist = max(dist, abs(a - b) + 1e-4)
    base = math.atan2(dy, dx)
    ang = math.acos(max(-1, min(1, (a * a + dist * dist - b * b) / (2 * a * dist))))
    j = (root[0] + a * math.cos(base + bend * ang), root[1] + a * math.sin(base + bend * ang))
    e = (root[0] + dist * math.cos(base), root[1] + dist * math.sin(base))
    return j, e

# ---------------------------------------------------------------- presets
# Every preset follows the book: torso twist (yaw_up != yaw_low, <=60 deg apart), opposing shoulder/hip tilt,
# a clear action line (line=[...] lists the joints it should run through), and the EXTREME frame of the motion.
# Limbs take either angles (up/fore, th/sh) or an IK target: to=(x, y) in head units from the pelvis
# center (y down), bend=+1/-1 picks which way the elbow/knee folds. Targets beyond reach are clamped.
# rto=(x, y) = target relative to the limb ROOT (shoulder/hip) in units of that limb's length: works at any head-count.
# fs_* = foreshortening factor for a segment pointing at/away from camera (1 = flat to camera).
# tags = Danbooru tags that describe the pose/camera to the model (Illustrious checkpoints read tags, not sentences).
PRESETS = {
 "flying_punch": dict(airborne=True, spine=62, pelvis=55, yaw_up=40, yaw_low=15, sroll=-6, hroll=8,
     head=dict(roll=-32, yaw=60), R=dict(up=78, fore=80, fs_up=0.85, fs_fore=0.8), L=dict(up=215, fore=115),
     RL=dict(th=185, sh=255), LL=dict(th=238, sh=262), line=[0, 1, 'pelvis', 13],
     tags="midair, flying, punching, from side, full body, outstretched arm, clenched hand, leaning forward, dynamic pose, foreshortening, motion lines, speed lines, wind",
     note="Superman punch: whole body one long diagonal; near fist slightly foreshortened toward camera."),
 "rising_kick": dict(airborne=False, spine=340, yaw_up=40, yaw_low=70, sroll=6, hroll=-10,
     head=dict(roll=18, yaw=55), R=dict(up=110, fore=40), L=dict(up=245, fore=255),
     RL=dict(th=62, sh=58), LL=dict(th=188, sh=183), support='L', line=[0, 1, 'pelvis', 13],
     tags="kicking, high kick, leg up, standing on one leg, fighting stance, clenched hands, dynamic pose, motion lines",
     note="Torso leans AWAY from the kick to counter-balance; support leg + spine form one C-curve."),
 "power_pole_swing": dict(airborne=False, spine=340, yaw_up=-15, yaw_low=35, sroll=-8, hroll=6,
     head=dict(roll=12, yaw=50), R=dict(to=(-0.80, -1.80), bend=1), L=dict(to=(-0.62, -1.95), bend=1),
     RL=dict(th=128, sh=172), LL=dict(th=222, sh=210), support='both', line=[7, 1, 'pelvis', 13],
     tags="holding staff, swinging, arms up, lunge, wind-up, twisted torso, dynamic pose, motion lines",
     note="Wind-up extreme: upper body coiled back 50 deg against hips; hands-to-back-foot is one big C."),
 "energy_blast": dict(airborne=False, spine=8, yaw_up=60, yaw_low=25, sroll=-5, hroll=7,
     head=dict(roll=8, yaw=65), R=dict(up=88, fore=90, fs_up=0.95, fs_fore=0.9), L=dict(up=82, fore=86, fs_up=0.9, fs_fore=0.85),
     RL=dict(th=215, sh=196), LL=dict(th=140, sh=172), support='both', line=[4, 1, 'pelvis', 13],
     tags="firing energy blast, outstretched arms, arms forward, palms forward, wide stance, from side, full body, dynamic pose, glowing, light rays",
     note="Side-on blast: arms level and nearly flat to camera (heavy foreshortening read as bending over - 2026-10-06). Back leg straight side, front curved."),
 "dash": dict(airborne=False, spine=35, pelvis=25, yaw_up=30, yaw_low=50, sroll=-8, hroll=8,
     head=dict(roll=-22, yaw=55), R=dict(up=110, fore=40), L=dict(up=232, fore=205),
     RL=dict(th=232, sh=255), LL=dict(th=100, sh=192), support='none', line=[0, 1, 'pelvis', 10],
     tags="running, sprinting, leaning forward, knee up, clenched hands, dynamic pose, speed lines, dust cloud",
     note="Contralateral: forward arm opposite forward leg. Head-to-back-foot one straight diagonal."),
 "orb_charge": dict(airborne=False, spine=40, pelvis=22, yaw_up=40, yaw_low=60, sroll=-8, hroll=8,
     head=dict(roll=-26, yaw=60), R=dict(up=232, fore=215), L=dict(up=92, fore=88, fs_up=0.95, fs_fore=0.9),
     RL=dict(th=232, sh=262), LL=dict(th=100, sh=188), support='none', line=[7, 1, 'pelvis', 10],
     tags="running, charging, lunging, outstretched arm, holding energy sphere, leaning forward, from side, full body, dynamic pose, speed lines, wind, debris",
     note="Charge with an energy orb (rasengan/chidori): lead arm thrust straight at the target, back arm trailing, low sprint diagonal from orb to back foot."),
 "ground_punch": dict(airborne=False, spine=55, pelvis=30, yaw_up=35, yaw_low=15, sroll=-12, hroll=8,
     head=dict(roll=-35, yaw=40), R=dict(rto=(0.45, 0.80), bend=1), L=dict(up=250, fore=300),
     RL=dict(rto=(-0.55, 0.62), bend=-1), LL=dict(rto=(0.45, 0.62), bend=-1), support='both', line=[4, 1, 'pelvis', 10],
     tags="punching the ground, fist on ground, crouching, ground cracking, shockwave, impact, flying rocks, dynamic pose, from side, full body",
     note="Downward smash: whole body drives through the fist into the ground; back arm flung up for counter-balance, compressed triangle."),
 "sand_command": dict(airborne=False, spine=348, pelvis=8, yaw_up=25, yaw_low=-10, sroll=9, hroll=-9,
     head=dict(roll=-8, yaw=-25), R=dict(up=258, fore=266), L=dict(up=152, fore=265),
     RL=dict(th=190, sh=182), LL=dict(th=168, sh=178), support='both', line=[4, 1, 'pelvis', 13],
     tags="standing, outstretched arm, open hand, arms crossed, calm, expressionless, swirling sand, sand wave, wind, floating hair, dynamic pose, from below, full body",
     note="Stillness against chaos: near-upright calm body, one arm sweeping out to command the effect; the FX carry the motion. Slight lean back, twist 35."),
 "crouch_spring": dict(airborne=False, spine=38, yaw_up=30, yaw_low=10, sroll=-10, hroll=6,
     head=dict(roll=-48, yaw=35), R=dict(to=(0.55, 0.55), bend=1), L=dict(up=245, fore=268),
     RL=dict(to=(-0.75, 0.62), bend=1), LL=dict(to=(0.70, 0.62), bend=-1), support='both', line=[0, 1, 'pelvis', 10],
     tags="squatting, crouching, hand on ground, looking ahead, about to jump, dynamic pose, from below, dust, wind",
     note="Anticipation extreme before a leap: compressed spring, triangle silhouette, head lifted toward the target."),
 "cloud_ride": dict(airborne=False, spine=32, pelvis=10, yaw_up=40, yaw_low=75, sroll=-8, hroll=8,
     head=dict(roll=-22, yaw=60), R=dict(up=245, fore=262), L=dict(up=72, fore=66),
     RL=dict(to=(-0.75, 0.95), bend=-1), LL=dict(to=(0.75, 0.95), bend=-1), support='both', line=[4, 1, 'pelvis', 13],
     tags="riding, standing on cloud, surfing, crouching, knees bent, leaning forward, pointing forward, flying, wind, floating hair, speed lines, dynamic pose, from side, full body",
     note="Surfer stance on a cloud/board: knees soft, chest leads, front arm points the way, back arm trails; one long diagonal from fingertip to back foot."),
 "leap_joy": dict(airborne=True, spine=352, yaw_up=0, yaw_low=25, sroll=8, hroll=-8,
     head=dict(roll=-10, yaw=10), R=dict(up=325, fore=338), L=dict(up=32, fore=22),
     RL=dict(th=168, sh=250), LL=dict(th=192, sh=262), line=[4, 1, 'pelvis', 10],
     tags="jumping, midair, arms up, legs tucked, open mouth, smile, happy, dynamic pose, from below, wind",
     note="Arched C-curve from raised hands through the back to folded legs."),
 "look_back_guard": dict(airborne=False, spine=6, yaw_up=150, yaw_low=125, sroll=7, hroll=-7,
     head=dict(roll=8, yaw=100), R=dict(up=200, fore=150), L=dict(up=160, fore=212),
     RL=dict(th=176, sh=181), LL=dict(th=203, sh=172), support='R', line=[0, 1, 'pelvis', 10],
     tags="from behind, looking back, looking over shoulder, fighting stance, clenched hands, dynamic pose",
     note="Back three-quarter: shoulders and hips turned 25 deg apart, face in profile over the shoulder."),
 "spin_slash": dict(airborne=False, spine=15, yaw_up=75, yaw_low=25, sroll=-12, hroll=10,
     head=dict(roll=5, yaw=65), R=dict(up=70, fore=55), L=dict(up=255, fore=235),
     RL=dict(th=150, sh=200), LL=dict(th=212, sh=176), support='both', line=[4, 1, 'pelvis', 13],
     tags="swinging, follow-through, motion blur, twisted torso, lunge, cloak, dynamic pose, dutch angle",
     note="Follow-through extreme: chest whipped 50 deg past the hips, lead arm extended along the swing arc."),
 # --- added 2026-10-14: compact silhouettes, all limbs on-screen, side/3-4 views ---
 "hero_landing": dict(airborne=False, spine=48, pelvis=20, yaw_up=20, yaw_low=5, sroll=-8, hroll=6,
     head=dict(roll=-38, yaw=15), R=dict(to=(0.15, 1.05), bend=1), L=dict(up=300, fore=318),
     RL=dict(to=(-0.35, 1.15), bend=1), LL=dict(to=(0.75, 0.55), bend=-1), support='both', line=[0, 1, 'pelvis', 10],
     tags="superhero landing, three-point landing, kneeling, one knee, fist on ground, looking at viewer, from below, impact, cracked ground, dust, dynamic pose, full body",
     note="Three-point landing: fist planted between the knees, back arm flung up, head lifted to camera. Compact triangle."),
 "fight_stance": dict(airborne=False, spine=10, pelvis=4, yaw_up=45, yaw_low=60, sroll=-6, hroll=6,
     head=dict(roll=-6, yaw=35), R=dict(up=125, fore=20), L=dict(up=150, fore=40),
     RL=dict(th=208, sh=188), LL=dict(th=150, sh=172), support='both', line=[0, 1, 'pelvis', 10],
     tags="fighting stance, fists up, guard, ready stance, from side, full body, dynamic pose, wind",
     note="Fighting-game idle: 3/4 turned, both fists up at chin height, wide stance, weight slightly back."),
 "ninja_run": dict(airborne=False, spine=48, pelvis=30, yaw_up=40, yaw_low=55, sroll=-8, hroll=8,
     head=dict(roll=-40, yaw=60), R=dict(up=218, fore=228), L=dict(up=232, fore=242),
     RL=dict(th=236, sh=262), LL=dict(th=105, sh=182), support='none', line=[0, 1, 'pelvis', 10],
     tags="ninja run, running, sprinting, arms behind back, leaning forward, low stance, from side, full body, dynamic pose, speed lines, dust",
     note="Low horizontal sprint, both arms trailing: one long diagonal from head to back foot."),
 "victory_fist": dict(airborne=False, spine=354, pelvis=4, yaw_up=20, yaw_low=5, sroll=8, hroll=-8,
     head=dict(roll=-12, yaw=15), R=dict(up=342, fore=350), L=dict(up=165, fore=118),
     RL=dict(th=196, sh=186), LL=dict(th=166, sh=176), support='both', line=[4, 1, 'pelvis', 10],
     tags="fist raised, arm up, victory pose, grin, confident, from below, wind, floating hair, dynamic pose, full body",
     note="Win pose: one fist straight up, slight back-arch, low camera."),
 # --- added 2026-10-15 from studying Reiq (comic pin-up/fan art): his pose + composition vocabulary, non-explicit framing ---
 # adults only; prompts keep "fully clothed" and the global anti-fanservice negatives. Never use these for Xiaohei.
 # kneel / low crouch / lying versions live in Splash-Batch/depth/poses3d.py (2D skeletons can't read them).
 "pinup_contrapposto": dict(airborne=False, spine=354, pelvis=10, yaw_up=20, yaw_low=40, sroll=10, hroll=-14,
     head=dict(roll=12, yaw=25), R=dict(rto=(0.30, 0.55), bend=-1), L=dict(up=200, fore=150),
     RL=dict(th=190, sh=186), LL=dict(th=158, sh=178), support='R', line=[0, 1, 'pelvis', 10],
     tags="standing, contrapposto, hand on hip, weight on one leg, confident, smirk, looking at viewer, from below, full body, dynamic pose, wind, floating hair",
     note="Reiq S-curve: hip thrown hard to the weight side, shoulders counter-tilted, hand on hip makes the triangle. Classic pin-up stance."),
 "glance_back_twist": dict(airborne=False, spine=8, pelvis=4, yaw_up=60, yaw_low=118, sroll=8, hroll=-8,
     head=dict(roll=10, yaw=-10), R=dict(up=205, fore=165), L=dict(up=150, fore=205),
     RL=dict(th=165, sh=176), LL=dict(th=198, sh=188), support='both', line=[0, 1, 'pelvis', 10],
     tags="looking back, looking over shoulder, twisted torso, upper body turned to viewer, three-quarter view, from side, full body, dynamic pose, floating hair",
     note="Hips turned away, chest swung back toward camera (80 deg twist via yaw_up/yaw_low), face toward viewer. Reads as a glance, not a rear view."),
 "hair_whip_turn": dict(airborne=False, spine=12, pelvis=6, yaw_up=70, yaw_low=25, sroll=-12, hroll=10,
     head=dict(roll=-18, yaw=60), R=dict(up=60, fore=40), L=dict(up=240, fore=210),
     RL=dict(th=212, sh=196), LL=dict(th=150, sh=170), support='L', line=[4, 1, 'pelvis', 13],
     tags="turning, spinning, hair whip, long hair flowing, motion blur, backhand, fighting stance, dutch angle, full body, dynamic pose, wind",
     note="Spin follow-through: shoulders whipped 45 deg past hips, lead arm swinging out, hair/FX trail the arc (Reiq frames action with hair and energy)."),
 "flying_kick": dict(airborne=True, spine=332, pelvis=300, yaw_up=60, yaw_low=80, sroll=-6, hroll=6,
     head=dict(roll=-10, yaw=70), R=dict(up=160, fore=60), L=dict(up=250, fore=230),
     RL=dict(th=168, sh=250), LL=dict(th=72, sh=76), line=[0, 1, 'pelvis', 13],
     tags="flying kick, jump kick, midair, leg extended, kicking, from side, full body, dynamic pose, speed lines, motion lines",
     note="Side-on jump kick: lead leg fully extended flat to camera, rear leg tucked, torso leaning back."),
 # --- character-sheet views (turnaround lineup; see `lineup` command) ---
 "landing_adult": dict(airborne=False, spine=50, pelvis=20, yaw_up=30, yaw_low=55, sroll=-8, hroll=8,
     head=dict(roll=-45, yaw=20), R=dict(up=172, fore=182), L=dict(up=285, fore=300),
     RL=dict(th=160, sh=265), LL=dict(th=95, sh=180), support='both', line=[7, 1, 'pelvis', 10],
     tags="superhero landing, three-point landing, kneeling, one knee, fist on ground, looking ahead, from below, dust, impact, full body",
     note="Adult-proportion superhero landing: rear knee down with shin flat behind, front foot planted, fist on the ground, back arm flung up."),
 "pinup_side": dict(airborne=False, spine=354, pelvis=6, yaw_up=86, yaw_low=98, sroll=4, hroll=-6,
     head=dict(roll=4, yaw=90), R=dict(up=176, fore=168), L=dict(up=188, fore=196),
     RL=dict(th=172, sh=184), LL=dict(th=190, sh=180), support='both', line=[0, 1, 'pelvis', 13],
     tags="from side, profile, side view, standing, arched back, full body",
     note="Side view: full profile facing right (arms and legs overlap like a real profile), slight back-arch S."),
 "startled_recoil": dict(airborne=False, spine=338, pelvis=350, yaw_up=20, yaw_low=45, sroll=-10, hroll=10,
     head=dict(roll=-14, yaw=20), R=dict(up=250, fore=330), L=dict(up=105, fore=25),
     RL=dict(th=196, sh=176), LL=dict(th=140, sh=200), support='R', line=[0, 1, 'pelvis', 10],
     tags="surprised, startled, recoiling, leaning back, hands up, open hands, open mouth, wide-eyed, one leg up, full body",
     note="Recoil: torso thrown back away from the scare, both palms up near the face, front knee lifted."),
 "pinup_back": dict(airborne=False, spine=4, pelvis=356, yaw_up=160, yaw_low=182, sroll=-9, hroll=12,
     head=dict(roll=-8, yaw=150), R=dict(up=196, fore=186), L=dict(rto=(0.12, 0.62), bend=-1),
     RL=dict(th=184, sh=181), LL=dict(th=167, sh=184), support='R', line=[1, 'pelvis', 10],
     tags="from behind, back, standing, contrapposto, hand on hip, full body",
     note="Back view: back to camera, hip thrown to the weight leg, one hand on hip, head turned a little."),
 "reach_foreshort": dict(airborne=False, spine=12, pelvis=6, yaw_up=15, yaw_low=40, sroll=-8, hroll=8,
     head=dict(roll=8, yaw=15), R=dict(up=238, fore=250, fs_up=0.32, fs_fore=0.40), L=dict(up=196, fore=168),
     RL=dict(th=190, sh=180), LL=dict(th=166, sh=178), support='both', line=[4, 1, 'pelvis', 13],
     tags="reaching towards viewer, outstretched hand, foreshortening, leaning forward, from below",
     note="Reach at camera: near arm foreshortened, chest leaning in, hips back."),
 # --- pin-up / fashion poses (adult proportions, 6.5-7.5 heads) ---
 "pinup_hands_behind_head": dict(airborne=False, spine=355, pelvis=10, yaw_up=12, yaw_low=28, sroll=8, hroll=-12,
     head=dict(roll=10, yaw=12), R=dict(to=(-0.35, -2.95), bend=-1), L=dict(to=(0.35, -2.95), bend=1),
     RL=dict(th=188, sh=180), LL=dict(th=160, sh=200), support='R', line=[0, 1, 'pelvis', 10],
     tags="arms behind head, hands behind head, contrapposto, hip pop, standing, looking at viewer, full body",
     note="Classic pin-up: elbows out, hands behind head, hip thrown to the weight leg, relaxed knee inward."),
 "pinup_over_shoulder": dict(airborne=False, spine=4, pelvis=356, yaw_up=150, yaw_low=170, sroll=-8, hroll=12,
     head=dict(roll=-6, yaw=100), R=dict(rto=(-0.12, 0.6), bend=1), L=dict(up=192, fore=176),
     RL=dict(th=180, sh=184), LL=dict(th=166, sh=200), support='R', line=[0, 1, 'pelvis', 10],
     tags="from behind, looking back, looking over shoulder, hand on hip, standing, full body",
     note="Back to camera, face turned over the shoulder, hand on hip, one knee bent."),
 "pinup_hand_in_hair": dict(airborne=False, spine=354, pelvis=10, yaw_up=18, yaw_low=38, sroll=10, hroll=-14,
     head=dict(roll=14, yaw=18), R=dict(to=(-0.25, -3.1), bend=-1), L=dict(to=(0.55, 0.05), bend=-1),
     RL=dict(th=190, sh=184), LL=dict(th=160, sh=196), support='R', line=[0, 1, 'pelvis', 10],
     tags="hand in own hair, hand on hip, contrapposto, s-curve, standing, looking at viewer, full body",
     note="S-curve: one hand lifting the hair, the other on the hip, head tilted into the raised arm."),
 "pinup_kneeling_arch": dict(airborne=False, spine=352, pelvis=4, yaw_up=12, yaw_low=26, sroll=6, hroll=-6,
     head=dict(roll=8, yaw=10), R=dict(to=(-0.35, -2.9), bend=-1), L=dict(to=(0.35, -2.9), bend=1),
     RL=dict(th=186, sh=180, fs_sh=0.3), LL=dict(th=174, sh=180, fs_sh=0.3), support='both', line=[0, 1, 'pelvis', 10],
     tags="kneeling, arched back, hands in own hair, looking at viewer, full body",
     note="Kneeling front view, shins pointing back (foreshortened), back arched, both hands in the hair."),
 "fashion_sitting_crossed": dict(airborne=False, spine=2, pelvis=0, yaw_up=55, yaw_low=75, sroll=4, hroll=-4,
     head=dict(roll=6, yaw=30), R=dict(up=160, fore=110), L=dict(up=175, fore=120),
     RL=dict(th=95, sh=180), LL=dict(th=100, sh=160), support='both', line=[0, 1, 'pelvis', 13],
     tags="sitting, crossed legs, on stool, hands on lap, looking at viewer, full body",
     note="Seated on a stool facing camera, thighs foreshortened toward viewer, one leg crossed over."),
 "fashion_runway_walk": dict(airborne=False, spine=358, pelvis=6, yaw_up=6, yaw_low=18, sroll=8, hroll=-12,
     head=dict(roll=2, yaw=0), R=dict(up=196, fore=186), L=dict(up=164, fore=176),
     RL=dict(th=174, sh=192), LL=dict(th=196, sh=170), support='R', line=[0, 1, 'pelvis', 10],
     tags="walking, runway, catwalk, crossed step, confident, looking at viewer, full body",
     note="Catwalk step: feet crossing the center line, hips swinging hard, arms loose."),
 "fashion_power_stance": dict(airborne=False, spine=0, pelvis=0, yaw_up=8, yaw_low=20, sroll=3, hroll=-4,
     head=dict(roll=-4, yaw=6), R=dict(to=(-0.55, 0.05), bend=1), L=dict(to=(0.55, 0.05), bend=-1),
     RL=dict(th=200, sh=186), LL=dict(th=160, sh=174), support='both', line=[0, 1, 'pelvis', 10],
     tags="hands on hips, legs apart, power pose, confident, looking at viewer, from below, full body",
     note="Wide stance, both hands on hips, slight low angle: confident fashion/superhero stance."),
 "fashion_ankle_cross": dict(airborne=False, spine=356, pelvis=8, yaw_up=16, yaw_low=32, sroll=7, hroll=-10,
     head=dict(roll=10, yaw=16), R=dict(to=(-0.55, 0.05), bend=1), L=dict(up=188, fore=178),
     RL=dict(th=165, sh=170), LL=dict(th=195, sh=190), support='R', line=[0, 1, 'pelvis', 13],
     tags="standing, crossed ankles, legs crossed, hand on hip, looking at viewer, full body",
     note="Standing with ankles crossed, hand on hip, gentle S-curve: catalog/fashion pose."),
 "stand_front": dict(airborne=False, spine=356, pelvis=6, yaw_up=0, yaw_low=8, sroll=3, hroll=-3,
     head=dict(roll=0, yaw=4), R=dict(up=197, fore=193), L=dict(up=163, fore=167),
     RL=dict(th=192, sh=188), LL=dict(th=168, sh=171), support='both', line=[0, 1, 'pelvis', 10],
     tags="standing, full body, looking at viewer",
     note="Neutral relaxed standing front view for character boards: arms hang at the sides, tiny contrapposto, face to camera."),
 "stand_back": dict(airborne=False, spine=358, pelvis=4, yaw_up=180, yaw_low=172, sroll=-3, hroll=3,
     head=dict(roll=0, yaw=175), R=dict(up=197, fore=193), L=dict(up=163, fore=167),
     RL=dict(th=192, sh=188), LL=dict(th=168, sh=171), support='both', line=[13, 'pelvis', 10],
     tags="from behind, standing, full body",
     note="Neutral relaxed back view for character boards: back to camera, face fully turned away, arms hanging, near-uniform stance."),
 # --- adult boudoir / glamour poses (solo; lying poses read best on landscape canvases) ---
 "boudoir_lying_side": dict(airborne=True, spine=90, pelvis=96, yaw_up=20, yaw_low=40, sroll=0, hroll=0,
     head=dict(roll=-20, yaw=15), R=dict(up=20, fore=300), L=dict(up=200, fore=240),
     RL=dict(th=268, sh=272), LL=dict(th=240, sh=295), line=[0, 1, 'pelvis', 10],
     tags="lying, on side, head rest, hand on own head, knee up, looking at viewer, full body, bed",
     note="Reclining on one side, head propped on the hand, top knee bent forward. Classic boudoir S-line."),
 "boudoir_lying_back_arch": dict(airborne=True, spine=272, pelvis=262, yaw_up=10, yaw_low=25, sroll=0, hroll=0,
     head=dict(roll=25, yaw=20), R=dict(up=268, fore=262), L=dict(up=285, fore=275),
     RL=dict(th=92, sh=96), LL=dict(th=55, sh=125), line=[4, 1, 'pelvis', 10],
     tags="lying, on back, arched back, arms above head, knee up, looking at viewer, full body, bed",
     note="On the back with arms stretched above the head, one knee raised, back arched."),
 "boudoir_lying_stomach": dict(airborne=True, spine=78, pelvis=90, yaw_up=10, yaw_low=20, sroll=0, hroll=0,
     head=dict(roll=-10, yaw=10), R=dict(up=172, fore=100), L=dict(up=186, fore=95),
     RL=dict(th=272, sh=20), LL=dict(th=268, sh=345), line=[0, 1, 'pelvis', 13],
     tags="lying, on stomach, propped up on elbows, legs up, crossed ankles, looking at viewer, full body, bed",
     note="On the stomach, chest raised on the elbows, shins kicked up behind (pin-up classic)."),
 "boudoir_kneel_sit_heels": dict(airborne=False, spine=356, pelvis=4, yaw_up=12, yaw_low=26, sroll=6, hroll=-6,
     head=dict(roll=10, yaw=10), R=dict(to=(-0.45, 0.65), bend=1), L=dict(to=(0.45, 0.65), bend=-1),
     RL=dict(th=205, sh=150, fs_th=0.35, fs_sh=0.3), LL=dict(th=155, sh=210, fs_th=0.35, fs_sh=0.3), support='both', line=[0, 1, 'pelvis', 10],
     tags="kneeling, sitting on heels, seiza, hands on thighs, looking at viewer, full body",
     note="Sitting back on the heels, knees forward (foreshortened), hands resting on the thighs."),
 "boudoir_reclining_seated": dict(airborne=False, spine=325, pelvis=300, yaw_up=70, yaw_low=85, sroll=0, hroll=0,
     head=dict(roll=25, yaw=50), R=dict(up=215, fore=200), L=dict(up=225, fore=205),
     RL=dict(th=95, sh=100), LL=dict(th=70, sh=150), support='both', line=[0, 1, 'pelvis', 13],
     tags="sitting, leaning back, arms behind back, one knee up, legs, looking at viewer, full body",
     note="Seated on the floor, leaning back on both hands, one leg straight, one knee up (side view)."),
 "boudoir_bent_over_look_back": dict(airborne=False, spine=72, pelvis=60, yaw_up=110, yaw_low=135, sroll=0, hroll=8,
     head=dict(roll=-60, yaw=70), R=dict(up=165, fore=170), L=dict(up=150, fore=160),
     RL=dict(th=186, sh=180), LL=dict(th=172, sh=182), support='both', line=[0, 1, 'pelvis', 10],
     tags="bent over, leaning forward, hands on knees, from behind, looking back, full body",
     note="Bent forward at the hips with hands toward the knees, seen from behind, face turned back to camera."),
}

def build(p, heads):
    P = props(heads)
    pts = {}
    pelvis = (0.0, 0.0)
    yu, yl = p['yaw_up'], p['yaw_low']
    twist = abs(((yu - yl + 180) % 360) - 180)
    if twist > 60:
        print(f"  ! ribcage/pelvis twist {twist:.0f} deg > 60 (book 2.6.4) - clamping", file=sys.stderr)
        yu = yl + math.copysign(60, ((yu - yl + 180) % 360) - 180)
    sp = p['spine']
    neck = add(pelvis, d(sp), P['torso'])
    def width(yaw, half):  # foreshorten the shoulder/hip line by facing; keep a sliver in pure profile
        c = math.cos(math.radians(yaw)); return math.copysign(max(abs(c), 0.18), c) * half
    sw, hw = width(yu, P['sho']), width(yl, P['hip'])
    # subject-right is image-left when facing camera: R = toward (axis-90)
    pts[1] = neck
    pts[2] = add(neck, d(sp - 90 + p['sroll']), sw); pts[5] = add(neck, d(sp + 90 + p['sroll']), sw)
    # pelvis is its own mass (book 2.3/7.3.1): the lumbar spine absorbs part of the lean, so by default the hip
    # line rotates only half as far as the ribcage. Override with pelvis=<compass deg of the pelvis 'up' axis>.
    pv = p.get('pelvis', sp * 0.5 if sp <= 180 else 360 - (360 - sp) * 0.5)
    pts[8] = add(pelvis, d(pv - 90 + p['hroll']), hw); pts[11] = add(pelvis, d(pv + 90 + p['hroll']), hw)
    for side, s, e, w in (('R', 2, 3, 4), ('L', 5, 6, 7)):
        a = p[side]
        if 'rto' in a:
            L = P['uarm'] * a.get('fs_up', 1) + P['farm'] * a.get('fs_fore', 1)
            a = dict(a, to=(pts[s][0] + a['rto'][0] * L, pts[s][1] + a['rto'][1] * L))
        if 'to' in a:
            pts[e], pts[w] = ik(pts[s], a['to'], P['uarm'] * a.get('fs_up', 1), P['farm'] * a.get('fs_fore', 1), a.get('bend', 1))
            continue
        pts[e] = add(pts[s], d(a['up']), P['uarm'] * a.get('fs_up', 1))
        pts[w] = add(pts[e], d(a['fore']), P['farm'] * a.get('fs_fore', 1))
    for side, h, k, an in (('RL', 8, 9, 10), ('LL', 11, 12, 13)):
        a = p[side]
        if 'rto' in a:
            L = P['thigh'] * a.get('fs_th', 1) + P['shin'] * a.get('fs_sh', 1)
            a = dict(a, to=(pts[h][0] + a['rto'][0] * L, pts[h][1] + a['rto'][1] * L))
        if 'to' in a:
            pts[k], pts[an] = ik(pts[h], a['to'], P['thigh'] * a.get('fs_th', 1), P['shin'] * a.get('fs_sh', 1), a.get('bend', 1))
            continue
        pts[k] = add(pts[h], d(a['th']), P['thigh'] * a.get('fs_th', 1))
        pts[an] = add(pts[k], d(a['sh']), P['shin'] * a.get('fs_sh', 1))
    hd = p['head']; ax = sp + hd['roll']; hy = math.radians(hd['yaw'])
    face = math.cos(hy)
    center = add(neck, d(ax), P['ntn'] * 0.95)
    nose = add(add(neck, d(ax), P['ntn']), d(ax + 90), math.sin(hy) * 0.30)
    eyec = add(nose, d(ax), P['eyeup'])
    if face > -0.2:  # face visible
        pts[0] = nose
        pts[14] = add(eyec, d(ax - 90), P['eye'] * max(face, 0.25) - 0.05 * math.sin(hy))
        pts[15] = add(eyec, d(ax + 90), P['eye'] * max(face, 0.25) + 0.05 * math.sin(hy))
    back = add(center, d(ax + 90), -math.sin(hy) * 0.22)
    if not math.sin(hy) < -0.7: pts[16] = add(back, d(ax - 90), P['ear'] * abs(face) + 0.05)
    if not math.sin(hy) > 0.7:  pts[17] = add(back, d(ax + 90), P['ear'] * abs(face) + 0.05)
    if math.sin(hy) > 0.7:  pts[16] = add(back, d(ax - 90), 0.05)   # profile right: only near (right) ear
    if math.sin(hy) < -0.7: pts[17] = add(back, d(ax + 90), 0.05)
    return pts, pelvis, twist

def checks(p, pts, pelvis, twist, heads):
    notes = [f"twist {twist:.0f} deg (book: >0 so masses never face the same way, <=60)"]
    if twist < 10: notes.append("  ! ribcage and pelvis face nearly the same way -> stiff (book 7.3.1)")
    tilt = abs(p['sroll'] - p['hroll'])
    notes.append(f"shoulder/hip counter-tilt {tilt:.0f} deg" + ("  ! add opposing tilts (contrapposto)" if tilt < 6 else ""))
    if not p.get('airborne'):
        sup = p.get('support', 'both')
        feet = [pts[10][0], pts[13][0]] if sup == 'both' else [pts[10][0]] if sup == 'R' else [pts[13][0]] if sup == 'L' else None
        if feet:
            cog = (pts[1][0] + pelvis[0] * 2) / 3
            lo, hi = min(feet) - 0.35, max(feet) + 0.35
            notes.append("balance ok (CoG over support)" if lo <= cog <= hi else
                         f"  CoG {cog:.2f} outside support [{lo:.2f},{hi:.2f}] -> reads as falling/lunging (fine if intended)")
    return notes

def place(pts, heads, W, H, size, at, mirror):
    ph = H * size / heads  # pixels per head: a STANDING figure would fill `size` of the canvas height
    xs = [v[0] for v in pts.values()]; ys = [v[1] for v in pts.values()]
    top = min(ys) - 0.5  # head extends ~half a head above nose/ears
    cx, cy = (min(xs) + max(xs)) / 2, (top + max(ys)) / 2
    out = {}
    for k, (x, y) in pts.items():
        x = (x - cx) * ph; y = (y - cy) * ph
        if mirror: x = -x
        out[k] = (W * at[0] + x, H * at[1] + y)
    if mirror:  # swap subject sides so labels stay correct after flipping
        sw = {2: 5, 3: 6, 4: 7, 8: 11, 9: 12, 10: 13, 14: 15, 16: 17}; sw.update({v: k for k, v in sw.items()})
        out = {sw.get(k, k): v for k, v in out.items()}
    clip = [k for k, (x, y) in out.items() if not (0 <= x < W and 0 <= y < H)]
    return out, ph, clip

def draw(pts, W, H, ph, debug_line=None):
    stick = max(4, ph * 0.045); rad = max(4, ph * 0.045)
    img = Image.new('RGB', (W, H), 'black'); dr = ImageDraw.Draw(img)
    for i, (a, b) in enumerate(LIMBS):
        if a in pts and b in pts:
            (x1, y1), (x2, y2) = pts[a], pts[b]
            L = math.hypot(x2 - x1, y2 - y1) / 2; ang = math.atan2(y2 - y1, x2 - x1)
            poly = [((x1 + x2) / 2 + L * math.cos(t) * math.cos(ang) - stick * math.sin(t) * math.sin(ang),
                     (y1 + y2) / 2 + L * math.cos(t) * math.sin(ang) + stick * math.sin(t) * math.cos(ang))
                    for t in [k * 2 * math.pi / 36 for k in range(36)]]
            dr.polygon(poly, fill=tuple(int(c * 0.6) for c in COLORS[i]))
    for k, (x, y) in pts.items():
        dr.ellipse([x - rad, y - rad, x + rad, y + rad], fill=COLORS[k])
    if debug_line:
        dr.line(debug_line, fill=(255, 255, 255), width=3)
    return img

def action_line(pts, pelvis_px, spec):
    ps = [pelvis_px if j == 'pelvis' else pts[j] for j in spec if j == 'pelvis' or j in pts]
    if len(ps) < 3: return None
    out = []  # Catmull-Rom through the listed joints
    ps = [ps[0]] + ps + [ps[-1]]
    for i in range(1, len(ps) - 2):
        p0, p1, p2, p3 = ps[i - 1], ps[i], ps[i + 1], ps[i + 2]
        for t in [k / 12 for k in range(13)]:
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t * t
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t ** 3) for c in (0, 1)))
    return out

def render(name, heads, W=832, H=1216, size=0.62, at=(0.5, 0.52), mirror=False, out=None, debug=None, quiet=False):
    p = PRESETS[name]
    pts, pelvis, twist = build(p, heads)
    pts['P'] = pelvis
    placed, ph, clip = place(pts, heads, W, H, size, at, mirror)
    pel = placed.pop('P')
    img = draw(placed, W, H, ph)
    if out: img.save(out)
    if debug:
        draw(placed, W, H, ph, action_line(placed, pel, p['line'])).save(debug)
    if not quiet:
        print(f"{name} @ {heads} heads -> {out or ''}")
        for n in checks(p, {k: v for k, v in pts.items() if k != 'P'}, pelvis, twist, heads): print("  " + n)
        if clip: print(f"  ! keypoints off-canvas: {clip} -> lower --size or move --at")
    return img, placed

def sheet(heads, out, W=832, H=1216):
    names = list(PRESETS); cols = 3; rows = math.ceil(len(names) / cols); tw, th = W // 3, H // 3
    S = Image.new('RGB', (cols * tw, rows * (th + 18)), (40, 40, 40)); dr = ImageDraw.Draw(S)
    for i, n in enumerate(names):
        p = PRESETS[n]; pts, pel, _ = build(p, heads); pts['P'] = pel
        placed, ph, _ = place(pts, heads, W, H, 0.6, (0.5, 0.52), False); pe = placed.pop('P')
        im = draw(placed, W, H, ph, action_line(placed, pe, p['line'])).resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + 18); S.paste(im, (x, y + 18)); dr.text((x + 4, y + 3), n, fill='white')
    S.save(out); print('sheet ->', out)

def lineup(names, heads, out, W=1344, H=768, size=0.86, debug=None):
    """Several presets side by side on one canvas (character reference sheet / turnaround)."""
    from PIL import ImageChops
    img = Image.new('RGB', (W, H), 'black'); dbg = img.copy(); n = len(names)
    for i, name in enumerate(names):
        p = PRESETS[name]; pts, pel, _ = build(p, heads); pts['P'] = pel
        placed, ph, clip = place(pts, heads, W, H, size, ((i + 0.5) / n, 0.5), False); pe = placed.pop('P')
        img = ImageChops.lighter(img, draw(placed, W, H, ph))
        if debug: dbg = ImageChops.lighter(dbg, draw(placed, W, H, ph, action_line(placed, pe, p['line'])))
        if clip: print(f"  ! {name}: keypoints off-canvas {clip}")
    img.save(out); print('lineup ->', out)
    if debug: dbg.save(debug)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('preset', nargs='?')
    ap.add_argument('--heads', type=float, default=3.5); ap.add_argument('--out'); ap.add_argument('--debug')
    ap.add_argument('--w', type=int, default=832); ap.add_argument('--h', type=int, default=1216)
    ap.add_argument('--size', type=float, default=0.62); ap.add_argument('--at', type=float, nargs=2, default=(0.5, 0.52))
    ap.add_argument('--mirror', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'list':
        for k, v in PRESETS.items(): print(f"{k:18s} {v['note']}\n{'':18s} tags: {v['tags']}")
    elif a.cmd == 'render':
        render(a.preset, a.heads, a.w, a.h, a.size, tuple(a.at), a.mirror, a.out, a.debug)
    elif a.cmd == 'lineup':
        lineup(a.preset.split(','), a.heads, a.out, a.w, a.h, a.size, a.debug)
    elif a.cmd == 'sheet':
        sheet(a.heads, a.out, a.w, a.h)
