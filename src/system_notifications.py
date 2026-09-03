def show_system_notification(title, message):
    try:
        from winotify import Notification

        notification = Notification(
            app_id="vRY // VALORANT Companion",
            title=title,
            msg=message,
        )
        notification.show()
        return True
    except Exception:
        return False
