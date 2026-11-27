# Adds Firebase Cloud Messaging to the Capacitor iOS AppDelegate, so the app gets an FCM token (the same kind of
# alert address as Android) instead of a raw Apple one. Run from app/: python3 ios-patch/AppDelegate-firebase.py
import re, sys
p = 'ios/App/App/AppDelegate.swift'; s = open(p).read()
if 'FirebaseMessaging' in s: sys.exit(0)
s = s.replace('import Capacitor', 'import Capacitor\nimport FirebaseCore\nimport FirebaseMessaging', 1)
s = re.sub(r'(didFinishLaunchingWithOptions launchOptions: \[UIApplication\.LaunchOptionsKey: Any\]\?\) -> Bool \{\n)',
           r'\1        if Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist") != nil { FirebaseApp.configure() }\n', s, count=1)
s = s.rstrip().rstrip('}') + '''
    // Alerts: hand Apple's device token to Firebase and give the app Firebase's token (what the alert server uses)
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        guard FirebaseApp.app() != nil else {
            NotificationCenter.default.post(name: .capacitorDidRegisterForRemoteNotifications, object: deviceToken); return
        }
        Messaging.messaging().apnsToken = deviceToken
        Messaging.messaging().token(completion: { (token, error) in
            if let error = error {
                NotificationCenter.default.post(name: .capacitorDidFailToRegisterForRemoteNotifications, object: error)
            } else if let token = token {
                NotificationCenter.default.post(name: .capacitorDidRegisterForRemoteNotifications, object: token)
            }
        })
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NotificationCenter.default.post(name: .capacitorDidFailToRegisterForRemoteNotifications, object: error)
    }
}
'''
open(p, 'w').write(s)
print('AppDelegate: Firebase added')
