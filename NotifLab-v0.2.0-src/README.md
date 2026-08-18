# NotifLab v0.2.0

A small Android notification test harness designed to exercise notification-listener apps such as RandoTone.

## Local tests
- Normal notification
- Burst of 5 notifications
- Repeated update of the same notification ID
- Same-ID update with `setOnlyAlertOnce(true)`
- 3 grouped child notifications plus a group summary
- Ongoing notification
- CALL category notification
- ALARM category notification
- Cancel all

The test notification channel is intentionally silent, so source-app audio does not interfere with RandoTone tests.

## Timed fire
NotifLab can post one normal notification repeatedly at a chosen interval.

- Interval: 50 ms to 3,600,000 ms (1 hour)
- Count: 1 to 10,000
- Count `0`: keep firing until Stop is pressed
- The first notification fires after one interval
- Start/Stop controls are available both in the Android app and on the LAN control page

Timed fire runs while the NotifLab process remains alive. Closing the app stops it.

## Wireless PC control
NotifLab starts a tiny HTTP server on TCP port `8765` while the app is open. The app shows its local IPv4 address, for example:

`http://192.168.1.123:8765/`

Open that address from a PC on the same local network. No PC software or cloud service is required. The page includes the local notification tests plus timed-fire Start/Stop controls.

This is a LAN-only convenience test server and has no authentication. Turn it off by closing NotifLab or leaving the test network when you do not need it.
