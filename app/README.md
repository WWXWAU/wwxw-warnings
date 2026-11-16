# WWXW Android app (test build)

A Capacitor app: `www/index.html` is the alerts screen (native Firebase push through the PushNotifications plugin)
with tabs that open the site's pages. Built by `.github/workflows/app-apk.yml` (Actions → "Android app" → Run workflow);
the APK is the run's `wwxw-app` artifact.

* `google-services.json` (or the secret `GOOGLE_SERVICES_JSON`): Firebase's file for the Android app
  `com.westweatherwatchers.app` (same Firebase project as the website's alerts). Without it the app builds but can't
  turn alerts on.
* `test-signing.keystore`: a fixed test key (password "android") so each test APK installs over the last one.
  Not for a store release — that gets its own private key.

Icons: `python3 make_icons.py` (from the logo in `wxvideo/`).
