# NotifLab v0.3.0

NotifLab is an Android notification test harness for exercising notification-listener apps such as RandoTone.

## v0.3: foreground-service survival

The LAN HTTP server and Timed Fire engine now run inside `NotifLabService`, a foreground service.

Expected behavior:
- Open NotifLab once to start the service.
- A silent ongoing `NotifLab service running` notification appears.
- Swipe NotifLab out of Recents.
- The LAN page on port 8765 remains reachable.
- A running timed-fire sequence continues.
- Reopening the app reconnects to the live runtime state.
- `Stop NotifLab service` intentionally shuts down the timer and LAN server.
- Android Settings -> Force stop still terminates the app/service.

The service uses Android's `specialUse` foreground-service type because this user-started local test harness does not fit the platform's other foreground-service categories.

## Notification tests
- Normal notification
- Burst
- Same-ID update
- `ONLY_ALERT_ONCE` update
- Group children + summary
- Ongoing notification
- CALL category
- ALARM category
- Timed fire: 50 ms to 1 hour interval; count 0 = until stopped

Both notification channels are silent. The foreground-service notification is ongoing, which lets listener apps such as RandoTone ignore it while still testing normal NotifLab notifications.

## Wireless PC control

While the foreground service is running, open the address shown in NotifLab from a PC on the same LAN, for example:

`http://192.168.1.123:8765/`

No cloud service or PC software is required. The server has no authentication and is intended only for a trusted local test network.
