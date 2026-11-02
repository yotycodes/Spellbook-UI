#!/usr/bin/env python3
"""Generate the 15 authored starter-pose skeletons (standalone/pose-starter/).

These are hand-set OpenPose-style joint coordinates drawn with the standard
OpenPose limb palette on a black canvas — the format the pose rail and Forge's
openpose ControlNet expect. They are app-generated content: run
this script to regenerate.

    python3 make_skeletons.py            # writes portrait/*.png and poses.json
"""
import json
import os
from PIL import Image, ImageDraw

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
W, H = 512, 768
LINE = 14
JOINT = 9
# OpenPose COCO limb palette (C++ rep colors), for pairs below
PALETTE = [(255, 0, 85), (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
           (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255),
           (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170)]
# joints: 0 nose 1 neck 2 r-shoulder 3 r-elbow 4 r-wrist 5 l-shoulder 6 l-elbow 7 l-wrist
#         8 r-hip 9 r-knee 10 r-ankle 11 l-hip 12 l-knee 13 l-ankle
PAIRS = [(1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13)]

# hand-set coordinates per pose. (x, y) on the 512x768 canvas.
# Proportion ruler: nose 100, neck 140, shoulders 150, hips 300, knees 460,
# ankles 600 (standing); arm: upper 95 / fore 85; thigh 150 / shin 135.
POSES = {
    "victory_arms_up": dict(
        tags="victorious, both arms raised high, fists clenched, standing tall, head tilted up, chest out, from front, full body",
        note="Victory: both wrists well above the head line, feet planted wide; reads as triumph from the front.",
        coords={0: (256, 104), 1: (256, 140), 2: (198, 152), 3: (170, 84), 4: (186, 28),
                5: (314, 152), 6: (342, 84), 7: (326, 28), 8: (238, 300), 9: (226, 462),
                10: (218, 598), 11: (274, 300), 12: (286, 462), 13: (294, 598)}),
    "uppercut_rising": dict(
        tags="uppercut, rising punch, from below, dynamic angle, bent knees, twisted torso, motion lines, action",
        note="Uppercut: rear arm coiled low then whipping up; body compressed, weight on the back leg.",
        coords={0: (272, 150), 1: (264, 190), 2: (206, 196), 3: (240, 266), 4: (300, 160),
                5: (322, 200), 6: (352, 268), 7: (330, 340), 8: (230, 330), 9: (200, 470),
                10: (196, 596), 11: (298, 334), 12: (330, 466), 13: (356, 588)}),
    "kick_side_high": dict(
        tags="side kick, high kick, one leg raised, kicking, from side, full body, dynamic, action, foreshortening",
        note="Side kick: kicking leg near-horizontal at hip height; supporting leg slightly bent, torso leaning away.",
        coords={0: (220, 140), 1: (236, 190), 2: (206, 196), 3: (158, 262), 4: (196, 318),
                5: (268, 196), 6: (292, 262), 7: (266, 314), 8: (256, 318), 9: (392, 292),
                10: (476, 286), 11: (288, 320), 12: (302, 468), 13: (310, 596)}),
    "superhero_landing": dict(
        tags="superhero landing, crouching, one fist on ground, dust, three-point landing, from front, low angle, action, dynamic pose",
        note="Three-point landing: crouched low, one fist to the floor, other arm flared wide for balance.",
        coords={0: (258, 266), 1: (250, 312), 2: (190, 322), 3: (158, 442), 4: (214, 556),
                5: (310, 324), 6: (376, 306), 7: (416, 246),
                8: (232, 470), 9: (162, 520), 10: (140, 588),
                11: (282, 472), 12: (350, 522), 13: (376, 588)}),
    "dash_running_blur": dict(
        tags="running, sprinting, full speed, motion blur, from side, leaning forward, speed lines, action",
        note="Sprint: torso leaned well past the hips, trailing leg kicked back, arms pumping opposite the legs.",
        coords={0: (322, 150), 1: (300, 196), 2: (244, 208), 3: (215, 282), 4: (255, 342),
                5: (352, 208), 6: (382, 258), 7: (340, 330),
                8: (244, 336), 9: (170, 420), 10: (90, 388),
                11: (296, 338), 12: (352, 454), 13: (340, 590)}),
    "sword_rest_shoulder": dict(
        tags="holding sword, resting blade on shoulder, relaxed stance, three quarter view, full body",
        note="Blade-on-shoulder idle stance: front arm relaxed, rear arm holding the hilt near the collarbone.",
        coords={0: (252, 120), 1: (252, 160), 2: (198, 170), 3: (192, 246), 4: (216, 318),
                5: (314, 168), 6: (352, 240), 7: (286, 180),
                8: (236, 304), 9: (220, 450), 10: (212, 590),
                11: (272, 306), 12: (290, 452), 13: (300, 592)}),
    "home_wave_hello": dict(
        tags="waving, one hand raised, friendly, standing weight shift, smiling, three quarter view, full body, casual",
        note="Wave hello: raised hand tilted slightly, weight over one hip, other hand relaxed at the side.",
        coords={0: (262, 108), 1: (258, 150), 2: (200, 160), 3: (182, 252), 4: (206, 320),
                5: (316, 160), 6: (346, 240), 7: (310, 86),
                8: (242, 300), 9: (230, 456), 10: (224, 592),
                11: (284, 300), 12: (298, 456), 13: (312, 594)}),
    "home_sit_couch_lean_back": dict(
        tags="sitting on couch, leaning back, relaxed, one arm along the backrest, legs crossed, from front, three quarter",
        note="Couch lean: hips set low, knees together and crossed, spine open behind the shoulders.",
        coords={0: (286, 196), 1: (268, 238), 2: (212, 248), 3: (180, 300), 4: (212, 262),
                5: (324, 252), 6: (350, 318), 7: (356, 252),
                8: (240, 390), 9: (196, 500), 10: (268, 566),
                11: (282, 392), 12: (300, 502), 13: (326, 570)}),
    "studio_arms_crossed": dict(
        tags="arms crossed, confident, standing, from front, chest out, full body, portrait distance, studio light",
        note="Arms crossed: forearms stacked over the chest line; a quietly certain wide stance.",
        coords={0: (256, 118), 1: (255, 164), 2: (198, 174), 3: (202, 244), 4: (272, 232),
                5: (312, 174), 6: (308, 244), 7: (240, 232),
                8: (238, 304), 9: (224, 452), 10: (216, 592),
                11: (278, 304), 12: (292, 452), 13: (300, 592)}),
    "studio_hand_in_pocket_lean": dict(
        tags="hand in pocket, leaning against wall, one knee bent, relaxed, from side, three quarter, full body",
        note="Wall lean: shoulders back against the surface, one heel hooked on the wall, hand buried in pocket.",
        coords={0: (258, 126), 1: (252, 172), 2: (196, 182), 3: (190, 258), 4: (240, 298),
                5: (308, 182), 6: (334, 254), 7: (296, 300),
                8: (250, 310), 9: (222, 456), 10: (238, 596),
                11: (282, 312), 12: (300, 450), 13: (280, 590)}),
    "studio_look_back_over_shoulder": dict(
        tags="looking back, over shoulder, walking away, three quarter back view, from behind, coat, full body",
        note="Over-shoulder glance mid-stride: hips away from camera, chest twisted toward the lens.",
        coords={0: (286, 122), 1: (262, 166), 2: (202, 176), 3: (186, 252), 4: (214, 320),
                5: (318, 176), 6: (344, 250), 7: (338, 320),
                8: (270, 310), 9: (300, 452), 10: (352, 570),
                11: (226, 312), 12: (238, 456), 13: (226, 594)}),
    "portrait_hand_hip_contrapposto": dict(
        tags="standing, contrapposto, one hand on hip, hip cocked, from front, waist up, portrait, elegant",
        note="Contrapposto with hand on hip: hips counter-tilted to the shoulders; a calm pose at portrait distance.",
        coords={0: (256, 132), 1: (256, 178), 2: (198, 188), 3: (218, 258), 4: (250, 306),
                5: (314, 188), 6: (348, 254), 7: (368, 316),
                8: (238, 322), 9: (222, 466), 10: (218, 602),
                11: (286, 318), 12: (300, 462), 13: (312, 600)}),
    "portrait_point_away": dict(
        tags="pointing, extended arm, gesturing offscreen, three quarter, from front, expression, upper body",
        note="Pointing offscreen: dominant arm at shoulder height, other arm easy; sell direction with the head.",
        coords={0: (262, 120), 1: (256, 166), 2: (198, 176), 3: (280, 214), 4: (404, 182),
                5: (314, 176), 6: (344, 250), 7: (352, 320),
                8: (242, 308), 9: (228, 454), 10: (222, 590),
                11: (280, 308), 12: (294, 454), 13: (304, 588)}),
    "portrait_thinking_pose": dict(
        tags="hand on chin, thinking, pensive, three quarter, portrait, waist up, standing",
        note="Thinking: hand to the chin, other arm folded beneath the working elbow.",
        coords={0: (258, 118), 1: (256, 164), 2: (200, 174), 3: (196, 246), 4: (262, 138),
                5: (312, 174), 6: (342, 240), 7: (296, 230),
                8: (244, 306), 9: (230, 452), 10: (226, 588),
                11: (278, 306), 12: (294, 452), 13: (306, 588)}),
    "outdoor_tree_pose_yoga": dict(
        tags="tree pose, yoga, one leg raised, balance, standing, calm, from front, full body",
        note="Tree pose: one foot pressed to the inner thigh, arms folded overhead on inhalation.",
        coords={0: (256, 116), 1: (256, 162), 2: (198, 172), 3: (172, 106), 4: (222, 62),
                5: (314, 172), 6: (340, 106), 7: (290, 62),
                8: (240, 306), 9: (226, 462), 10: (218, 600),
                11: (276, 306), 12: (310, 388), 13: (252, 440)}),
}

FIXES = {"line_val": 0}
for name, rec in POSES.items():
    rec = dict(rec)
    for bad in ("ii slightly", "在", "全球"):
        rec["note"] = rec.get("note", "").replace(bad, "").replace("  ", " ")
    POSES[name] = rec
os.makedirs(os.path.join(HERE, "portrait"), exist_ok=True)
with open(os.path.join(HERE, "poses-15.json"), "w") as _f:
    json.dump({k: {k2: v2 for k2, v2 in v.items() if k2 != "coords"} for k, v in POSES.items()},
              _f, indent=1)


def draw(name, rec):
    im = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)
    c = rec["coords"]
    for n, (i, j) in enumerate(PAIRS):
        color = PALETTE[n % len(PALETTE)]
        d.line([c[i], c[j]], fill=color, width=LINE)
    for (x, y) in c.values():
        d.ellipse([x - JOINT, y - JOINT, x + JOINT, y + JOINT], fill=(0, 255, 255))
    im.save(os.path.join(HERE, "portrait", f"{name}_adult.png"))
    return name


for name, rec in POSES.items():
    draw(name, rec)
print("wrote", len(POSES), "skeletons to", os.path.join(HERE, "portrait"))
