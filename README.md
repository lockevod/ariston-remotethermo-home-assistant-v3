# Ariston NET / Chaffolink — maintained fork

Fork of [fustom/ariston-remotethermo-home-assistant-v3](https://github.com/fustom/ariston-remotethermo-home-assistant-v3)
with fixes for current Home Assistant and the current Ariston cloud. Chaffoteaux
**Chaffolink** uses the same remotethermo cloud and has been reported working:
log in with your Chaffolink e-mail and password and keep the default API URL.

**Requires Home Assistant 2026.1 or newer** (tested on 2026.1.3 and 2026.11.0).

Changes in 0.20.0:
- Setup no longer fails when the cloud answers HTTP 500 on the `busErrors` or
  energy endpoints (upstream issues 497, 503, 509). Those sensors stay unavailable
  until the endpoint recovers; climate and hot water work normally.
- When the gateway answers HTTP 500 to the batched data request ("Gateway
  error ... InternalError", upstream issue 492, seen on GALEVO / Chaffolink),
  data is fetched in small chunks instead, and items that fail live are read
  from the cloud cache. Slower (about a minute per refresh) but it works.
- Zones the app hides (`isHidden`) are ignored: no phantom thermostats and a
  smaller data request.
- Debug logs no longer contain the session token, account details (name,
  e-mail, phone), address/GPS or gateway serial that the ariston library logs.
- Heating can be switched off from the thermostat even when the zone has no
  "Off" mode: Off sets the plant to Summer (hot water stays on). New
  "plant mode" select (Summer / Winter / OFF) to switch the boiler itself.
- New "central heating" switch. On zones without room sensor (gateway
  "virtual" thermostat) it raises/lowers the zone comfort temperature to
  max/min, which makes the gateway send / stop the heat request over the bus:
  no wired thermostat (TA) needed, plant stays in Winter. Otherwise it
  switches the plant Winter / Summer. Use it from automations (e.g. follow Tado
  heating demand) or as the heater of a Generic Thermostat.
- Zones without a room sensor show no current temperature instead of 0 °C.
- Cloud errors during polling are reported once as a normal "unavailable"
  warning instead of a traceback on every poll.
- Climate and water heater provide the `native_*` temperature API of
  HA 2026.11 (the old one stops working in 2027.11) and keep the old names
  for earlier 2026 releases.
- After changing a setting, every entity of the boiler updates at once
  (e.g. setting DHW temperature from the water heater also updates the DHW
  number entity) instead of waiting for the next poll.
- Parameters your boiler does not report no longer create broken number
  entities.
- Device and entry fall back to "Ariston" when the cloud returns an empty name.
- Diagnostics download (device page → ⋮ → Download diagnostics) with
  credentials, gateway serial, location and plant name redacted.

Install with HACS: *HACS → ⋮ → Custom repositories →*
`https://github.com/lockevod/ariston-remotethermo-home-assistant-v3`
(type *Integration*), install, restart, then *Settings → Devices & services →
Add integration → Ariston*. If you had the upstream version installed, remove it
from HACS first (same `ariston` domain; your config entry is kept).

---

# 🚀 Co-Maintainers Wanted!

Hello everyone! 

Thank you to everyone who uses, stars, and contributes to this project. 

Due to work commitments and a busy schedule, I am no longer able to dedicate the time this project deserves. To keep the repository active and moving forward, I am looking for **co-maintainers** or a **new primary maintainer** to help lead the project.

### How You Can Help:
* **Triage Issues:** Review, label, and respond to incoming issue reports.
* **Review Pull Requests:** Help test, review, and merge community contributions.
* **Maintenance & Enhancements:** Keep dependencies updated and work on planned roadmap features.

### Interested?
If you've enjoyed using this project and would like to step up as a maintainer, please:
1. Write an email to me.
2. Briefly introduce yourself and share any prior experience or ideas you have for the project.

Even if you can only contribute a few hours a month, your help would be hugely appreciated!

Thanks for being part of the community! 🙌

[![CodeQL](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/codeql.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![HACS Action](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/hacs.yml/badge.svg)](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/hacs.yml)
[![Validate with hassfest](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/hassfest.yml/badge.svg)](https://github.com/fustom/ariston-remotethermo-home-assistant-v3/actions/workflows/hassfest.yml)
# Ariston NET remotethermo integration for Home Assistant
This integration inspired by chomupashchuk fantastic work https://github.com/chomupashchuk/ariston-remotethermo-home-assistant-v2
But it does not use Ariston website. It uses Ariston API what I reversed engineered.


| [This integration](https://github.com/fustom/ariston-remotethermo-home-assistant-v3)  | [Chomupashchuk's v2 integration](https://github.com/chomupashchuk/ariston-remotethermo-home-assistant-v2) |
| ------------- | ------------- |
| Uses real API  | Uses Ariston website  |
| Faster set/get data  | Sometimes needs minutes to set/get data |
| Easy to setup with UI | Not so easy to setup (only with configuration.yaml) |
| Integration & devices & entites | Only entites |
| Proper asynchronous integration, clean code | Hard to understand and maintain (ariston.py has more than 4000 lines) |
| Less sensors, switches, etc |  More sensors, switches, etc |
| New code, may contains lot of bugs | Old, tested code |

## TODO
- Localization. Avaliable in english, catalan, italian, russian and ukranian.
- More sensors, switches, binary sersors, selectors, services.
- Exception handling.
- More logs.
- Unit tests.
- Fun.

## Integration was tested on and works with:
- Ariston Alteas One 24
- Ariston Velis Evo
- Ariston Velis Lux
- Ariston Lydos Hybrid

Feel free to test something else and create new issue / pull request if something goes wrong.

## Installation
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fustom&repository=ariston-remotethermo-home-assistant-v3&category=integration) or copy ariston folder to your configuration/custom_components path.
Use the add integration UI to set up your device.

| ![Kazam_screenshot_00003](https://user-images.githubusercontent.com/6751243/146653448-ff7b6f9d-cbf1-4555-9a75-61bf68bc9d3e.png) | ![Kazam_screenshot_00004](https://user-images.githubusercontent.com/6751243/146653484-52e39d78-7c6f-44ae-888d-acf246147290.png) | ![Kazam_screenshot_00010](https://user-images.githubusercontent.com/6751243/147890590-6c4ebf38-16d9-421f-9b81-8f43298ec62f.png) |
:-------------------------:|:-------------------------:|:-------------------------:

![Kazam_screenshot_00011](https://user-images.githubusercontent.com/6751243/147890611-54ae2d28-bf5a-45f8-ba92-e7a00a22615c.png)

![Kazam_screenshot_00012](https://user-images.githubusercontent.com/6751243/147989103-cdac510f-e6f6-461f-a88e-b8ff0204c34f.png)

| ![Kazam_screenshot_00013](https://user-images.githubusercontent.com/6751243/148247717-5211c01c-561f-4a4e-b4b5-47a680e04a68.png) | ![Kazam_screenshot_00009](https://user-images.githubusercontent.com/6751243/146657797-ed14b741-595a-48a6-9126-1acca3beb69f.png) |
:-------------------------:|:-------------------------:

<h1 align="center">Peace Love Freedom</h1>
