from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    DOMAIN,
    CONF_CLIMATE,
    CONF_ROOM_SENSORS,
    CONF_ROOM_TARGET,
    CONF_WINDOW_SENSORS,
    CONF_INTERVAL_SEC,
    CONF_DEADBAND,
    CONF_STEP_MAX,
    CONF_STEP_MIN,
    CONF_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW,
    CONF_TRV_MIN,
    CONF_TRV_MAX,
    CONF_COOLDOWN_SEC,
    CONF_MIN_ON_SEC,
    CONF_MIN_OFF_SEC,
    CONF_BOOST_DURATION_SEC,
    CONF_VALVE_EXERCISE_DAYS,
    CONF_VALVE_EXERCISE_SEC,
    CONF_VALVE_SWITCH_ENTITY,
    CONF_MAX_OFFSET_STEP,
    CONF_ENABLE_LEARNING,
    CONF_STUCK_ENABLE,
    CONF_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP,
    CONF_STUCK_STEP,
    CONF_MIN_OFFSET_CHANGE,
    CONF_NO_LEARN_SUMMER,
    CONF_WINDOW_OPEN_NO_LEARN_MIN,
    CONF_HEATING_ALPHA,
    CONF_OVERSHOOT_THRESHOLD,
    CONF_PREDICT_MINUTES,
    CONF_STABLE_LEARN_SECONDS,
    CONF_STABLE_LEARN_ALPHA,
    CONF_OFFSET_DECAY_RATE,
    CONF_OFFSET_DECAY_THRESHOLD,
    CONF_OFFSET_LEARN_THRESHOLD,
    CONF_MAX_STUCK_BIAS,
    CONF_TTT_ALPHA,
    CONF_TTT_SOFT_MIN,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_FORECAST_TYPE,
    CONF_OUTDOOR_SENSOR,
    CONF_WEATHER_BASE_TEMP,
    CONF_WEATHER_MAX_COMP,
    CONF_PRESENCE_ENTITY,
    CONF_OCCUPANCY_ACTIVITY,
    CONF_OCCUPANCY_HOLD_MIN,
    CONF_LEARNED_PREHEAT_ENABLE,
    CONF_LEARNED_PREHEAT_LEAD_MIN,
    CONF_ECO_ENABLE,
    DEFAULT_OCCUPANCY_HOLD_MIN,
    DEFAULT_LEARNED_PREHEAT_ENABLE,
    DEFAULT_LEARNED_PREHEAT_LEAD_MIN,
    CONF_ECO_OFFSET,
    CONF_PREDICTIVE_FACTOR,
    CONF_PID_KP,
    CONF_PID_KI,
    CONF_PID_KD,
    CONF_HUMIDITY_SENSOR,
    CONF_COOLDOWN_REDUCTION_FACTOR,
    CONF_PRESET_COMFORT_TEMP,
    CONF_PRESET_ECO_TEMP,
    CONF_PRESET_AWAY_TEMP,
    CONF_PRESET_SLEEP_TEMP,
    CONF_SHOW_ADVANCED,
    CONF_CONTROL_PROFILE,
    CONTROL_PROFILES,
    CONTROL_PROFILE_OPTIONS,
    PROFILE_COMFORT,
    PROFILE_CUSTOM,
    CONF_WORKDAY_SENSOR,
    CONF_PREHEAT_MORNING_READY,
    CONF_PREHEAT_MORNING_READY_WEEKEND,
    CONF_PREHEAT_EVENING_READY,
    CONF_PREHEAT_LEAD_MIN,
    CONF_NIGHT_OPEN_WINDOWS,
    DEFAULT_PRESET_COMFORT_TEMP,
    DEFAULT_PRESET_ECO_TEMP,
    DEFAULT_PRESET_AWAY_TEMP,
    DEFAULT_PRESET_SLEEP_TEMP,
    DEFAULT_PREHEAT_LEAD_MIN,
    DEFAULT_NIGHT_OPEN_WINDOWS,
    DEFAULTS,
    RUNTIME_OPTION_KEYS,
)
from .helpers import normalize_entity_list as _normalize_entity_list

_LOGGER = logging.getLogger(__name__)


def _same_option(a: Any, b: Any) -> bool:
    """Сравнение options без ложных custom из‑за 600 vs 600.0."""
    if a is b:
        return True
    if a is None or b is None:
        return a is b
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


class SmartThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для Smart Thermostat."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Шаг настройки основных параметров."""
        errors = {}

        if user_input is not None:
            room_sensors = _normalize_entity_list(user_input[CONF_ROOM_SENSORS])
            if not room_sensors:
                errors["base"] = "no_room_sensor"
            else:
                user_input[CONF_ROOM_SENSORS] = room_sensors

            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_CLIMATE) == user_input[CONF_CLIMATE]:
                    errors["base"] = "already_configured"
                    break

            if not errors:
                climate_name = user_input[CONF_CLIMATE].split(".")[-1]
                sensors_name = ", ".join([s.split(".")[-1] for s in room_sensors[:3]])
                if len(room_sensors) > 3:
                    sensors_name += "…"
                title = f"Smart Thermostat: {climate_name} ↔ {sensors_name}"
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_CLIMATE): EntitySelector(
                EntitySelectorConfig(domain="climate", multiple=False)
            ),
            vol.Required(CONF_ROOM_SENSORS): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor", multiple=True, device_class="temperature"
                )
            ),
            vol.Optional(CONF_WINDOW_SENSORS): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(CONF_ROOM_TARGET, default=22.0): NumberSelector(
                NumberSelectorConfig(
                    min=5.0,
                    max=30.0,
                    step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return SmartThermostatOptionsFlow(config_entry)


class SmartThermostatOptionsFlow(config_entries.OptionsFlow):
    """Options: простая форма + опциональный шаг «Расширенные»."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry
        self._pending: dict[str, Any] = {}

    def _opts(self) -> dict:
        return dict(self._config_entry.options)

    def _get_option(self, key, default=None):
        return self._opts().get(key, DEFAULTS.get(key, default))

    def _get_entity_option(self, key):
        """Пусто → vol.UNDEFINED (иначе HA: Entity None is neither a valid entity ID)."""
        val = self._opts().get(key, DEFAULTS.get(key))
        if val is None or val == "":
            return vol.UNDEFINED
        return val

    def _get_time_option(self, key):
        """Пустое время → UNDEFINED (предпрогрев выкл; не навязывать чужой слот)."""
        val = self._opts().get(key, DEFAULTS.get(key))
        if val is None or val == "":
            return vol.UNDEFINED
        s = str(val).strip()
        if len(s) == 5 and s.count(":") == 1:
            return f"{s}:00"
        return s

    def _apply_control_profile(self, updates: dict[str, Any]) -> dict[str, Any]:
        """При смене профиля подставить бандл knobs. custom / без смены — как есть."""
        prev = self._get_option(CONF_CONTROL_PROFILE, PROFILE_COMFORT)
        new = updates.get(CONF_CONTROL_PROFILE, prev)
        if new == prev or new == PROFILE_CUSTOM:
            return updates
        bundle = CONTROL_PROFILES.get(str(new))
        if not bundle:
            return updates
        # Бандл перекрывает устаревшие значения knobs из формы
        # (напр. boost_duration_sec ещё со старого профиля).
        applied = dict(updates)
        applied.update(bundle)
        applied[CONF_CONTROL_PROFILE] = new
        _LOGGER.info(
            "Применён профиль %s → %s для %s",
            prev,
            new,
            self._config_entry.entry_id,
        )
        return applied

    def _merge_and_save(self, updates: dict[str, Any]):
        """Мержит обновления с текущими options — скрытые ключи не затираются."""
        updates = self._apply_control_profile(updates)
        merged = dict(self._config_entry.options)
        merged.update(updates)
        for key in RUNTIME_OPTION_KEYS:
            if key not in merged and key in self._config_entry.options:
                merged[key] = self._config_entry.options[key]

        # Expert переопределил knobs профиля → пометить custom, чтобы
        # повторный save простой формы не затёр тонкую настройку.
        profile = merged.get(CONF_CONTROL_PROFILE, PROFILE_COMFORT)
        bundle = CONTROL_PROFILES.get(str(profile))
        if bundle and any(
            not _same_option(merged.get(k), v)
            for k, v in bundle.items()
            if k in merged
        ):
            merged[CONF_CONTROL_PROFILE] = PROFILE_CUSTOM

        changed = [
            k for k, v in merged.items() if self._config_entry.options.get(k) != v
        ]
        if changed:
            _LOGGER.info(
                "Изменены опции для %s: %s",
                self._config_entry.entry_id,
                changed,
            )
        return self.async_create_entry(title="", data=merged)

    def _simple_schema(self) -> vol.Schema:
        """Понятные поля для обычного пользователя."""
        return vol.Schema(
            {
                vol.Optional(
                    CONF_CONTROL_PROFILE,
                    default=self._get_option(
                        CONF_CONTROL_PROFILE, PROFILE_COMFORT
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(CONTROL_PROFILE_OPTIONS),
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="control_profile",
                    )
                ),
                vol.Optional(
                    CONF_VALVE_SWITCH_ENTITY,
                    default=self._get_entity_option(CONF_VALVE_SWITCH_ENTITY),
                ): EntitySelector(
                    EntitySelectorConfig(domain="switch", multiple=False)
                ),
                vol.Optional(
                    CONF_WINDOW_SENSORS,
                    default=self._get_option(CONF_WINDOW_SENSORS, []),
                ): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional(
                    CONF_OUTDOOR_SENSOR,
                    default=self._get_entity_option(CONF_OUTDOOR_SENSOR),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature",
                        multiple=False,
                    )
                ),
                vol.Optional(
                    CONF_WEATHER_ENTITY,
                    default=self._get_entity_option(CONF_WEATHER_ENTITY),
                ): EntitySelector(
                    EntitySelectorConfig(domain="weather", multiple=False)
                ),
                vol.Optional(
                    CONF_PRESENCE_ENTITY,
                    default=self._get_option(CONF_PRESENCE_ENTITY, []),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["person", "device_tracker", "binary_sensor"],
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_OCCUPANCY_ACTIVITY,
                    default=self._get_option(CONF_OCCUPANCY_ACTIVITY, []),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["light", "switch", "binary_sensor", "media_player"],
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_OCCUPANCY_HOLD_MIN,
                    default=self._get_option(
                        CONF_OCCUPANCY_HOLD_MIN, DEFAULT_OCCUPANCY_HOLD_MIN
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=240,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="мин",
                    )
                ),
                vol.Optional(
                    CONF_LEARNED_PREHEAT_ENABLE,
                    default=bool(
                        self._get_option(
                            CONF_LEARNED_PREHEAT_ENABLE,
                            DEFAULT_LEARNED_PREHEAT_ENABLE,
                        )
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_LEARNED_PREHEAT_LEAD_MIN,
                    default=self._get_option(
                        CONF_LEARNED_PREHEAT_LEAD_MIN,
                        DEFAULT_LEARNED_PREHEAT_LEAD_MIN,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=15,
                        max=120,
                        step=15,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="мин",
                    )
                ),
                vol.Optional(
                    CONF_ECO_ENABLE,
                    default=self._get_option(CONF_ECO_ENABLE, True),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_NIGHT_OPEN_WINDOWS,
                    default=bool(
                        self._get_option(
                            CONF_NIGHT_OPEN_WINDOWS, DEFAULT_NIGHT_OPEN_WINDOWS
                        )
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_PRESET_COMFORT_TEMP,
                    default=self._get_option(
                        CONF_PRESET_COMFORT_TEMP, DEFAULT_PRESET_COMFORT_TEMP
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5.0,
                        max=30.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_PRESET_ECO_TEMP,
                    default=self._get_option(
                        CONF_PRESET_ECO_TEMP, DEFAULT_PRESET_ECO_TEMP
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5.0,
                        max=30.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_PRESET_AWAY_TEMP,
                    default=self._get_option(
                        CONF_PRESET_AWAY_TEMP, DEFAULT_PRESET_AWAY_TEMP
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5.0,
                        max=30.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_PRESET_SLEEP_TEMP,
                    default=self._get_option(
                        CONF_PRESET_SLEEP_TEMP, DEFAULT_PRESET_SLEEP_TEMP
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5.0,
                        max=30.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_LEARNING,
                    default=self._get_option(CONF_ENABLE_LEARNING),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_NO_LEARN_SUMMER,
                    default=self._get_option(CONF_NO_LEARN_SUMMER),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_BOOST_DURATION_SEC,
                    default=self._get_option(CONF_BOOST_DURATION_SEC),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=30,
                        max=7200,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_VALVE_EXERCISE_DAYS,
                    default=self._get_option(CONF_VALVE_EXERCISE_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=60,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="дн.",
                    )
                ),
                vol.Optional(
                    CONF_SHOW_ADVANCED,
                    default=bool(self._get_option(CONF_SHOW_ADVANCED, False)),
                ): BooleanSelector(),
            }
        )

    def _advanced_schema(self) -> vol.Schema:
        """Экспертные knobs — без изменения семантики."""
        return vol.Schema(
            {
                # Предпрогрев — опционально; пустое время = выкл (не навязывать
                # чужое семейное расписание всем пользователям интеграции).
                vol.Optional(
                    CONF_WORKDAY_SENSOR,
                    default=self._get_entity_option(CONF_WORKDAY_SENSOR),
                ): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", multiple=False)
                ),
                vol.Optional(
                    CONF_PREHEAT_MORNING_READY,
                    default=self._get_time_option(CONF_PREHEAT_MORNING_READY),
                ): TimeSelector(),
                vol.Optional(
                    CONF_PREHEAT_MORNING_READY_WEEKEND,
                    default=self._get_time_option(
                        CONF_PREHEAT_MORNING_READY_WEEKEND
                    ),
                ): TimeSelector(),
                vol.Optional(
                    CONF_PREHEAT_EVENING_READY,
                    default=self._get_time_option(CONF_PREHEAT_EVENING_READY),
                ): TimeSelector(),
                vol.Optional(
                    CONF_PREHEAT_LEAD_MIN,
                    default=self._get_option(
                        CONF_PREHEAT_LEAD_MIN, DEFAULT_PREHEAT_LEAD_MIN
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=180,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="мин",
                    )
                ),
                vol.Optional(
                    CONF_INTERVAL_SEC, default=self._get_option(CONF_INTERVAL_SEC)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=1800,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_DEADBAND, default=self._get_option(CONF_DEADBAND)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=2.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_STEP_MAX, default=self._get_option(CONF_STEP_MAX)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1,
                        max=5.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_STEP_MIN, default=self._get_option(CONF_STEP_MIN)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05,
                        max=2.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_LEARN_RATE_FAST,
                    default=self._get_option(CONF_LEARN_RATE_FAST),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_LEARN_RATE_SLOW,
                    default=self._get_option(CONF_LEARN_RATE_SLOW),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_MIN_OFFSET_CHANGE,
                    default=self._get_option(CONF_MIN_OFFSET_CHANGE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_MAX_OFFSET_STEP,
                    default=self._get_option(CONF_MAX_OFFSET_STEP),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05,
                        max=1.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C/тик",
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_OPEN_NO_LEARN_MIN,
                    default=self._get_option(CONF_WINDOW_OPEN_NO_LEARN_MIN),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=1440,
                        step=5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    CONF_TRV_MIN, default=self._get_option(CONF_TRV_MIN)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5.0,
                        max=25.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_TRV_MAX, default=self._get_option(CONF_TRV_MAX)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=15.0,
                        max=35.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_COOLDOWN_SEC, default=self._get_option(CONF_COOLDOWN_SEC)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_MIN_ON_SEC, default=self._get_option(CONF_MIN_ON_SEC)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_MIN_OFF_SEC, default=self._get_option(CONF_MIN_OFF_SEC)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_VALVE_EXERCISE_SEC,
                    default=self._get_option(CONF_VALVE_EXERCISE_SEC),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=600,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_STUCK_ENABLE, default=self._get_option(CONF_STUCK_ENABLE)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_STUCK_SECONDS, default=self._get_option(CONF_STUCK_SECONDS)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=300,
                        max=86400,
                        step=60,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_STUCK_MIN_DROP,
                    default=self._get_option(CONF_STUCK_MIN_DROP),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=3.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_STUCK_STEP, default=self._get_option(CONF_STUCK_STEP)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05,
                        max=5.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_MAX_STUCK_BIAS,
                    default=self._get_option(CONF_MAX_STUCK_BIAS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1.0,
                        max=10.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_HEATING_ALPHA,
                    default=self._get_option(CONF_HEATING_ALPHA),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.01, max=0.5, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_OVERSHOOT_THRESHOLD,
                    default=self._get_option(CONF_OVERSHOOT_THRESHOLD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1,
                        max=2.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_PREDICT_MINUTES,
                    default=self._get_option(CONF_PREDICT_MINUTES),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=60,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    CONF_STABLE_LEARN_SECONDS,
                    default=self._get_option(CONF_STABLE_LEARN_SECONDS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=300,
                        max=3600,
                        step=60,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_STABLE_LEARN_ALPHA,
                    default=self._get_option(CONF_STABLE_LEARN_ALPHA),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05, max=0.5, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_OFFSET_DECAY_RATE,
                    default=self._get_option(CONF_OFFSET_DECAY_RATE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=0.1, step=0.001, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_OFFSET_DECAY_THRESHOLD,
                    default=self._get_option(CONF_OFFSET_DECAY_THRESHOLD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_OFFSET_LEARN_THRESHOLD,
                    default=self._get_option(CONF_OFFSET_LEARN_THRESHOLD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1,
                        max=2.0,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_TTT_ALPHA, default=self._get_option(CONF_TTT_ALPHA)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.05, max=0.5, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_TTT_SOFT_MIN, default=self._get_option(CONF_TTT_SOFT_MIN)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2,
                        max=30,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    CONF_WEATHER_FORECAST_TYPE,
                    default=self._get_option(CONF_WEATHER_FORECAST_TYPE, "hourly"),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=["hourly", "daily"],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_WEATHER_BASE_TEMP,
                    default=self._get_option(CONF_WEATHER_BASE_TEMP, 5.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=-10.0,
                        max=20.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_WEATHER_MAX_COMP,
                    default=self._get_option(CONF_WEATHER_MAX_COMP, 5.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=10.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_ECO_OFFSET,
                    default=self._get_option(CONF_ECO_OFFSET, -3.0),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=-10.0,
                        max=0.0,
                        step=0.5,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(
                    CONF_PREDICTIVE_FACTOR,
                    default=self._get_option(CONF_PREDICTIVE_FACTOR, 0.3),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.05, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PID_KP, default=self._get_option(CONF_PID_KP, 0.6)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1, max=2.0, step=0.1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PID_KI, default=self._get_option(CONF_PID_KI, 0.05)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=0.5, step=0.01, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_PID_KD, default=self._get_option(CONF_PID_KD, 0.1)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.05, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_COOLDOWN_REDUCTION_FACTOR,
                    default=self._get_option(CONF_COOLDOWN_REDUCTION_FACTOR, 0.3),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=0.8,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="коэфф.",
                    )
                ),
                vol.Optional(
                    CONF_HUMIDITY_SENSOR,
                    default=self._get_entity_option(CONF_HUMIDITY_SENSOR),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor", device_class="humidity", multiple=False
                    )
                ),
            }
        )

    async def async_step_init(self, user_input=None):
        """Простые настройки. При show_advanced → шаг advanced."""
        if user_input is not None:
            self._pending = dict(user_input)
            if user_input.get(CONF_SHOW_ADVANCED):
                return await self.async_step_advanced()
            return self._merge_and_save(self._pending)

        return self.async_show_form(
            step_id="init",
            data_schema=self._simple_schema(),
        )

    async def async_step_advanced(self, user_input=None):
        """Расширенные настройки (для опытных)."""
        if user_input is not None:
            updates = dict(self._pending)
            updates.update(user_input)
            return self._merge_and_save(updates)

        return self.async_show_form(
            step_id="advanced",
            data_schema=self._advanced_schema(),
        )
