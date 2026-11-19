# LMS Guardian (standalone)

The same LMS tools as the main extension, but with no bot, token, panel or account: it works only for the person who installs it.
Features: Moodle themes, compact layout, phone fixes, "not submitted + time left" badges and a Deadlines list, download-all-files zip, GPA calculator (college scale, can fill from the SIS grades you open yourself).

- `src/`: standalone-only code (floating panel, SIS grade capture, manifests).
- `build.mjs`: `node standalone/build.mjs` builds `dist/` from `src/` plus the shared files in `extension/`
  (`lms-theme.js`, `lms-tools.js`, `gpa.js`, `gpa-ui.js`, `jszip.min.js`, SIS readers cut from `extension/lib.js`).
- `dist/chromium/` Chrome, Edge, Brave, Opera (MV3, Load unpacked). `dist/firefox/` Firefox (MV2, desktop + Android).
  `dist/lms-guardian.user.js` Violentmonkey/Tampermonkey (the only no-signing route on Firefox for Android). Zips are in `dist/`.
- `guide.html`: English + Arabic install guide for every main browser (published at `/standalone/guide.html` on the Pages site).

Rebuild and commit `dist/` after changing any shared file. Not verified live: the Firefox build and the Violentmonkey install flow.
