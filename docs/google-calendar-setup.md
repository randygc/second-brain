# Google Calendar setup for the five-day preview

This is a local Desktop OAuth connection for the standalone program, separate from the Calendar plugin connected to the chat. Do not paste passwords, client JSON contents, authorization codes, or tokens into chat.

## 1. Select a Cloud project and enable Calendar API

In [Google Cloud Console](https://console.cloud.google.com/), select or create a project for Second Brain. Open APIs & Services → Library, find Google Calendar API, and enable it. No paid service or billing setup is part of this slice; stop rather than enabling billing if prompted unexpectedly.

## 2. Configure consent and the test account

Open [Google Auth Platform](https://console.cloud.google.com/auth/overview). If it is not configured, use Get Started and complete the application name, support/contact email, and audience details. For a personal Gmail account use External; in Audience, keep the application in Testing and add the Google account containing your calendar as a test user. An organizational account may have different administrator policies.

The program requests these scopes in its login flow:

- `calendar.events.owned.readonly`: read events on calendars you own.
- `calendar.calendars.readonly`: read calendar properties, including the timezone.

If Data Access requires selecting them, select those exact read-only scopes. Neither grants event editing. Calendar selection in the program further limits which calendar it actually reads, but OAuth scopes are not permissions for just one selected calendar.

## 3. Download a Desktop client

In Google Auth Platform → Clients, choose Create Client → Desktop app, name it, and create it. Download its JSON locally. Store it as `.local/google-client.json` inside this project; `.local/` is Git-ignored. Restrict the downloaded file's permissions to your account. Use a Desktop client, not a web application client, for this local command-line slice.

No values are sent to GitHub, CI, Linear, or the chat. The client file is consumed locally; the auth command writes the token file with owner-only permissions.

## 4. Install support and authorize

Run the virtual-environment/install/auth commands in the README from the repository root. Review Google's consent screen, sign in with the intended account, and approve read-only access. The maintained Google OAuth library handles the browser authorization and local callback. If Google shows a testing/unverified warning, check that it is your own project and intended scopes before proceeding; organization policies may prevent authorization.

The token is saved at `.local/google-token.json`. Do not share it. If you change scopes, re-run authorization and approve the updated permissions. If the token expires or access is revoked, reauthorize; errors do not become empty search results.

## 5. Verify your real calendar

Run the README's preview command with your selected calendar and September 28, 2026. Compare original descriptions against your supplied cases, particularly Example 6's seven actions and four double-dash bullets. This live check is required before calling issue #2 fully verified. Do not manufacture source line breaks from the old chat-connector snapshot.

Reference: [Google's Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python), [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth), [events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).
