// Spellbook notifier: posts one macOS notification as "Spellbook" (its own bundle id + icon), then exits.
// usage: SpellbookNotifier <title> <body> [sound-name]
import Foundation
import UserNotifications

let args = CommandLine.arguments
let title = args.count > 1 ? args[1] : "Spellbook"
let body = args.count > 2 ? args[2] : ""
let soundName = args.count > 3 ? args[3] : ""

let center = UNUserNotificationCenter.current()
let done = DispatchSemaphore(value: 0)
center.requestAuthorization(options: [.alert, .sound]) { granted, error in
    guard granted else {
        FileHandle.standardError.write("notifications not allowed: \(error?.localizedDescription ?? "denied")\n".data(using: .utf8)!)
        done.signal(); return
    }
    let c = UNMutableNotificationContent()
    c.title = title
    c.body = body
    c.sound = soundName.isEmpty ? .default : UNNotificationSound(named: UNNotificationSoundName(soundName))
    center.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { err in
        if let err { FileHandle.standardError.write("post failed: \(err.localizedDescription)\n".data(using: .utf8)!) }
        done.signal()
    }
}
_ = done.wait(timeout: .now() + 20)
exit(0)
