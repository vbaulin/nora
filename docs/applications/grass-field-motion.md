# Grass and Field Motion Intelligence

Grass is a visible sensor. Its color, motion, texture, and response to light can reveal wind, water stress, mowing, shade, and disturbance.

## What It Observes

- Movement between frames as a wind proxy.
- Green index drift over the day.
- Yellowing or browning after heat or dry periods.
- Mowing or trampling events.
- Shade timing and daily light profile.
- Texture change after watering or rain.

## Why It Is Powerful

The board can infer environmental state without specialized sensors. A cheap camera plus repeated local analysis becomes a field instrument. picoClaw sees a trend summary, not a pile of frames.

## Chain

```text
capture every 15 minutes
-> color index
-> frame difference / motion score
-> day/night and shade classification
-> JSONL journal
-> daily grass condition summary
```

## Useful Skills

- `canopy_motion_index`: motion score from frame deltas.
- `wind_from_grass`: estimates wind direction or intensity from movement.
- `water_stress_color`: tracks dulling/yellowing.
- `mowing_event_detect`: sudden height/texture change.
- `daily_light_profile`: brightness and shade cycle.
- `adaptive_interval`: samples more often when movement or color changes.

## Example Real Change

The board notices green index dropping every afternoon and recovering after sunset. picoClaw creates an experiment that increases capture rate around peak heat, then learns a `heat_stress_window` skill. Future monitors only wake picoClaw when the stress window is unusually long.

