# Test Glowtrack with your WiZ, LIFX or WLED lights

Glowtrack can make **WiZ**, **LIFX** and **WLED** lights follow the album colours of whatever is playing
on your Mac, the same way it drives Govee floor lamps. That support was written from each product's
published protocol and checked against pretend lights, but **it has never run on a real one**.

If you own one of these lights, about five minutes of your time tells us whether it works. A report that
says "it just worked" is as useful as a bug report.

## Before you start

- A Mac with Apple silicon and macOS 13 or later, and the light on the **same Wi-Fi network** as the Mac.
- Download the latest Glowtrack from the [releases page](https://github.com/omerham/glowtrack/releases/latest)
  (any design; they are the same app). Unzip it, move it to Applications, and open it the first time with
  right-click, then Open.
- You do not need a Govee lamp: Glowtrack should still run and drive your other light. (That combination is
  untested too, so say so if it does not work.)
- Nothing is permanent: you can remove the light from Glowtrack at any time, and the light itself is not changed.

Check the light's own setup first:

| Light | What it needs |
|---|---|
| **WiZ** | Local communication switched on in the WiZ app (Settings, Security, *Allow local communication*). [WiZ says it is on by default](https://faq.wizconnected.com/hc/en/3-wiz/faq/168-disabling-local-communication); if you turned it off, Glowtrack cannot reach the bulb. |
| **LIFX** | Nothing special. Glowtrack talks to the bulb over your local network (UDP port 56700). |
| **WLED** | Receiving UDP realtime switched on in WLED (Config, Sync Interfaces). Glowtrack sends colours as "DRGB" realtime packets to UDP port 21324 and uses WLED's normal web address for on and off. If colours never change, check this first. |

## The test

1. Open Glowtrack, play a song, and open the dashboard from the menu bar icon.
2. Go to **Settings, Other lights**.
3. Press **Scan**. WiZ and LIFX bulbs are found automatically. For a WLED strip, choose WLED, type its
   IP address (shown in your router or the WLED app) and press **Add**.
4. Add the light. Give it a name you will recognise, and choose whether it follows the **left** or **right**
   lamp (with no Govee lamps it does not matter which).
5. Watch the light for a minute or two while a song plays, and skip to a song with very different colours.
6. Try the dashboard's power button and brightness slider, and pause the music.

## What to look at

- Did **Scan** find it, or did you have to add it by IP address?
- Does it **follow the colours** of the album cover? Do they look right?
- Is there a **delay** compared with the music or with a Govee lamp? Roughly how much?
- Does it **flicker**, jump or fade smoothly?
- Does **brightness**, **power off** and **power on** work?
- For a WLED strip, do the colours spread along the strip in a sensible way?
- Anything else odd, even small.

## Send your result

Use the short form: **[Test report for WiZ, LIFX or WLED](https://github.com/omerham/glowtrack/issues/new?template=other_lights_test.yml)**
(it needs a free GitHub account). You can also open **Report a problem** in Glowtrack's Settings.

Please **do not post IP addresses**. Brand and model are enough.

No GitHub account? Say what happened in the thread of the pinned *Looking for testers* issue,
or ask someone to post it for you.

## If nothing happens

- Run Scan again, or add the light by its IP address.
- Make sure the Mac and the light are on the same network (not a guest network) and that Glowtrack was
  allowed to use the local network (System Settings, Privacy & Security, Local Network).
- Check the setup row in the table above for your light.
- The log has details: `tail -n 30 ~/Library/Logs/GoveeSpotifySync.log`. Paste the end of it into your
  report, with anything personal removed.

Thank you. Every report helps, and the first testers get named in the release notes if they want to be.
