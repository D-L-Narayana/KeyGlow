# How KeyGlow talks to the keyboard

Everything here was observed on one machine: Legion Pro 7i Gen 10 (16IAX10H, type 83F5), Legion Space 2.1.11.31.

## Two HID devices

| Device | Usage page | What it is |
|---|---|---|
| `VID_048D&PID_C193&MI_01` | `0x59` (Lighting and Illumination) | Standard HID LampArray, 318 lamps, 51-byte feature reports |
| `VID_048D&PID_C197&COL02` | `0xFF89` (vendor) | Lenovo's own channel, 960-byte feature reports, report ID 7 |

Lamp indices on the LampArray: 0-100 are the keys; the rest are the rear lights, the front bar and the logo. KeyGlow sorts them by the position and purpose each lamp reports.

## The switch that matters

Out of the box the firmware runs its own Legion Space profile and ignores LampArray colour updates, even though it accepts them without an error.
A feature report on the vendor channel changes who is in charge:

```
07 AA 01 00 00   -> the PC drives the lights ("Dynamic Lighting")
07 AA 01 00 01   -> the keyboard runs its own profile again
```

(padded with zeros to 960 bytes). Lenovo's lighting module logs this as `SwitchDynamicMode: [0: Dynamic Lighting. 1: KB Autonomous.]`.

KeyGlow's sequence:

1. Start: send `07 AA 01 00 00`, then LampArray control report `06 00` (AutonomousMode off), then stream colours.
2. While running: repeat step 1's two reports every 2 seconds. This is harmless when KeyGlow already has control and recovers after sleep.
3. Stop: LampArray `06 01`, then `07 AA 01 00 01`. The keyboard resumes the profile it was showing.

Nothing is stored in the keyboard and no profile is written.

## Sending colours

Standard LampArray reports:

- `04` LampMultiUpdate: up to 8 lamps per report (`04, count, flags, 8 x u16 lamp id, 8 x RGBI`). Set flags bit 0 on the last report of a frame.
- `05` LampRangeUpdate: one colour for a range of lamps.

Send intensity `255`. The value the keyboard reports in its lamp attributes is a level count, not a value to send back; sending `1` gives an almost dark keyboard.

## Reading back what the keyboard shows

`GetFeature` with report ID 7 on the vendor channel returns the live state: a 4-byte header (`07 03 8E 02`), then 5-byte entries `zone id (u16 LE), R, G, B`.
Zone ids: 1-167 keys, 501-510 front bar, 1001-1018 rear lights, 1501 logo (130 zones in total).
KeyGlow uses this once after Start to confirm the keyboard is really showing its colours.

## Speed

Measured through the read-back above: the firmware shows about 12 new frames a second on this route.
Sending full 318-lamp frames faster than about 20 a second makes it worse (2-6 a second), so KeyGlow sends 15 frames a second.

## Not used

The vendor channel has other commands as well (profiles, brightness). KeyGlow does not send any of them.
