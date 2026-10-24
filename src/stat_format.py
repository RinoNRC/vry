import math


STATS_PENDING = "Итоги матча ещё не опубликованы API или недоступны. Статистика другой игры не подставляется."


def recent_stats_caption(player):
    stats = player.get("recentStats") or {}
    count = stats.get("matches", 0)
    available = stats.get("availableMatches", 0)
    status = stats.get("status", "loading")
    limit = stats.get("requestedMatches", 1)
    prefix = "HS% и K/D: последний завершённый рейтинговый матч" if limit == 1 else f"HS% и K/D: последние {limit} рейтинговых матчей"
    if status == "loading":
        return f"{prefix} · загрузка ({count}/{available or limit})"
    if status == "empty":
        return f"{prefix} · нет завершённых матчей"
    if status == "unavailable":
        return f"{prefix} · API временно недоступен"
    coverage = f" · для HS%: {stats['hsMatches']}" if stats.get("hsMatches", count) < count else ""
    return f"{prefix} · учтено {count}" + (f" из {available}, часть недоступна" if status == "partial" else "") + coverage


def format_stat(value, suffix=""):
    try:
        if value is None or isinstance(value, bool) or not math.isfinite(float(value)):
            return "—"
    except (TypeError, ValueError):
        return "—"
    return f"{value}{suffix}"
