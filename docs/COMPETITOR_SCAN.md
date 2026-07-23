# Competitor and naming scan

Scan date: 2026-07-23
Authenticated GitHub account: `KanadeK` (account ID `121669563`)

## Naming decision

The public GitHub search returned no repository for the exact project name
`Greenhouse Steward` and no repository for the exact slug
`greenhouse-steward`. The intended remote, `KanadeK/greenhouse-steward`, also
did not exist at scan time.

The project therefore keeps the name **Greenhouse Steward** and the repository
slug **greenhouse-steward**. The fallback name, GrowRule Local, is not needed.

## Sampled public repositories

`Last push` describes code activity. `Updated` can also change because of
repository metadata or stars. Dates are UTC.

| Repository | Stars | Last push / Updated | Main capabilities | Overlap and difference |
|---|---:|---|---|---|
| [Dpineda1996/IoT-Greenhouse-Temperature-and-Irrigation-Controller-Node-Red](https://github.com/Dpineda1996/IoT-Greenhouse-Temperature-and-Irrigation-Controller-Node-Red) | 3 | 2023-08-11 / 2026-06-24 | Raspberry Pi, Node-RED, MQTT, MySQL, temperature, humidity, VPD, day/night thresholds, alerts, fans, irrigation, fallback sensor values, and CSV export | The broadest overlap in the sample, but it does not combine crop profiles, deterministic anomaly explanations, a simulation-first relay contract, ESP32 firmware, and a maximum actuator duration. |
| [ghaith-jbali/Smart-Greenhouse-IoT-System](https://github.com/ghaith-jbali/Smart-Greenhouse-IoT-System) | 2 | 2024-11-08 / 2026-04-21 | ESP32, MQTT, Node-RED, four environmental metrics, CSV data, several actuators, a dashboard, and Gemini advice | It covers the sensor set and device path, but its advice can depend on an external API and it lacks deterministic offline crop rules, explained anomalies, stale-sensor safety, and a relay time cap. |
| [songzhengliang/Greenhouse-Anomaly-Detection-in-Environmental-Sensor-Data-Using-TinyML](https://github.com/songzhengliang/Greenhouse-Anomaly-Detection-in-Environmental-Sensor-Data-Using-TinyML) | 0 | 2026-04-28 / 2026-04-28 | Local ESP32-S3 sensing, charts, training data, anomaly models, and virtual heating, ventilation, cooling, and misting decisions | It overlaps on local anomaly work and virtual actions, but not on MQTT, soil moisture, light, crop profiles, irrigation rules, daily/weekly trends, or relay safety limits. |
| [achidoang/Greenhouse-iot-MQTT-Compose](https://github.com/achidoang/Greenhouse-iot-MQTT-Compose) | 1 | 2025-03-09 / 2025-07-05 | Hydroponic lettuce monitoring, MQTT, pH/TDS/environment data, automatic/manual actuators, alerts, Android offline storage, and device profiles | It overlaps on MQTT, thresholds, offline caching, monitoring, and control. Its device profiles are not crop profiles, and it does not provide explained anomalies, stale-sensor fail-safe behavior, or simulation-first actuation. |
| [Olen/homeassistant-plant](https://github.com/Olen/homeassistant-plant) | 840 | 2026-07-20 / 2026-07-19 | Home Assistant plant devices, species data, per-plant thresholds, DLI/VPD, problem states, hysteresis, and unavailable-sensor handling | This is closest on plant profiles and health explanations, but it is a Home Assistant component rather than a standalone local greenhouse service and has no CSV/MQTT adapter pair, relay simulation, or ESP32 example. |
| [filipnet/greenhouse](https://github.com/filipnet/greenhouse) | 4 | 2023-03-30 / 2026-02-05 | ESP8266, TLS MQTT, temperature/humidity, pump/light relays, heartbeat, Node-RED, and a pump timeout emergency stop | It strongly overlaps on MQTT and maximum pump duration. Its scope is narrower and does not include profiles, anomaly explanations, CSV, trends, or all four required metrics. |
| [lucadibello/in-house-greenhouse](https://github.com/lucadibello/in-house-greenhouse) | 132 | 2023-10-26 / 2026-07-20 | Raspberry Pi sensing, automatic watering, React Native, GraphQL/PostgreSQL, statistics, and alerts | It overlaps on monitoring, watering, statistics, and alerts. It is service-centered rather than offline-first and does not include MQTT/CSV adapters, crop rules, explained anomalies, or a relay hard limit. |
| [tabaraei/Smart-Greenhouse](https://github.com/tabaraei/Smart-Greenhouse) | 22 | 2024-02-10 / 2026-07-11 | Arduino/Wemos, temperature, humidity and soil sensing, Flutter, a local Django service, threshold irrigation, SD logging, and notifications | It overlaps on local monitoring, thresholds, and irrigation. It lacks the complete sensor set, crop profiles, anomaly and stale-sensor analysis, daily/weekly trends, and the simulation safety contract. |
| [Python-IoT/Smart-IoT-Planting-System](https://github.com/Python-IoT/Smart-IoT-Planting-System) | 235 | 2018-03-21 / 2026-07-07 | LoRa/MQTT, STM32/Raspberry Pi/Django, environmental sensing, device status, and several irrigation modes | Its feature breadth is high, but its last code push is old and it does not offer a local-first single-machine experience, explainable crop rules, a simulation-first actuator, or an ESP32 example. |
| [dvcorreia/greenscale](https://github.com/dvcorreia/greenscale) | 9 | 2022-07-18 / 2024-01-31 | REST/MQTT, event logic, automatic actions, web monitoring, and a microservice architecture | The architecture is adjacent, but the repository is archived and explicitly incomplete. It lacks crop profiles, CSV input, explained anomalies, stale-sensor safety, and the ESP32 contract. |

Additional narrower implementations inspected were
[`Silvio347/smart-greenhouse-pid-iot`](https://github.com/Silvio347/smart-greenhouse-pid-iot),
[`jdupl/iot-greenhouse-ctrl`](https://github.com/jdupl/iot-greenhouse-ctrl), and
[`dmlond/greenhouse_mqtt_microcontroller`](https://github.com/dmlond/greenhouse_mqtt_microcontroller).

## Overlap judgment and differentiation

No active project in the sample overlaps more than roughly 70 percent of this
MVP. Each close project concentrates on one or two parts: hardware control,
plant thresholds, anomaly modeling, or MQTT firmware.

Greenhouse Steward keeps a narrower and testable combination:

- local-first FastAPI and SQLite operation with deterministic CSV input;
- MQTT and CSV adapters behind the same domain service;
- editable tomato and herb crop profiles;
- every rule records the observed value, applicable threshold, and practical
  recommendation;
- anomalies and stale sensors force a safe state;
- relay behavior is simulated by default and cannot exceed a configured
  maximum on-time;
- daily and weekly trends plus an ESP32 synthetic-data firmware example.

The README uses the bounded claim: **A sample of public repositories found no
active project with both the same name and a highly isomorphic feature set.**
This is a documented sample, not a uniqueness claim.

## Search method

The scan used authenticated GitHub CLI searches for the exact name, exact slug,
and combinations of `greenhouse`, `MQTT`, `monitoring`, `irrigation`,
`automation`, `ESP32`, `dashboard`, and `anomaly detection`. The ten entries
above were then inspected through their GitHub repository metadata and README
content.

The `agent-reach` executable was unavailable in this environment, so its
documented GitHub route, the official `gh` CLI, was used directly. The scan was
read-only.
