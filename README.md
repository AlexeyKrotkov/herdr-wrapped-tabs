# Wrapped Tabs for Herdr

Show all tabs in each workspace on wrapped lines below Herdr's tab bar. The list appears automatically when Herdr starts and follows workspace and tab changes.

## Install

Requires Herdr 0.7.5 or newer and Python 3 with `curses` (macOS or Linux).

```sh
herdr plugin install AlexeyKrotkov/herdr-wrapped-tabs
```

The list appears automatically on the next Herdr server start. To show it immediately in existing tabs of a running session, run:

```sh
herdr plugin action invoke local.wrapped-tabs.refresh
```

## Use

- Click a tab to open it. Hover to underline it.
- Focus the list pane and use Left/Right or `h`/`l` to select a tab, then Enter to open it.
- The active Herdr tab stays highlighted, and working tabs keep their red dot while selected.
- Scroll with the mouse wheel, Up/Down, `j`/`k`, or Page Up/Page Down when needed.

The list wraps to as many rows as it needs, up to half the tab area's height. Longer lists scroll inside the pane. Herdr currently gives split panes at least 10% of the available height, so short lists may leave empty space. The native tab bar stays visible.

## Disable

Remove the list from every workspace and prevent it from returning on startup:

```sh
herdr plugin action invoke local.wrapped-tabs.remove-all
herdr plugin disable local.wrapped-tabs
```

To enable it again:

```sh
herdr plugin enable local.wrapped-tabs
herdr plugin action invoke local.wrapped-tabs.refresh
```

The plugin leaves tabs with an existing multi-pane layout unchanged.
