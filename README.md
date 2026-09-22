# Wrapped Tabs for Herdr

Shows every tab in each workspace in a wrapped list immediately below Herdr's native tab bar. The list is a plugin pane in each tab, so it persists when you switch tabs or workspaces. Startup and workspace events add it to existing and new tabs automatically.

## Controls

- Click a tab name to switch to it.
- Focus the list pane, then use Left/Right or `h`/`l` to choose a tab and Enter to open it.
- Use Up/Down, `j`/`k`, Page Up/Page Down, or the mouse wheel to scroll when the list is taller than its pane.

The pane grows with wrapped rows, up to half of the available tab area. If the list is longer, scroll it inside the pane. Herdr 0.7.5 clamps split panes to at least 10% of that area, so a short list may still have empty rows. The native tab bar remains visible because the plugin API cannot hide it.

## Install

Requires Herdr 0.7.5 or newer and Python 3 with the standard `curses` module.

Install from GitHub:

```sh
herdr plugin install AlexeyKrotkov/herdr-wrapped-tabs
herdr plugin action invoke local.wrapped-tabs.refresh
```

For local development, clone the repository and link its directory instead:

```sh
herdr plugin link /absolute/path/to/herdr-wrapped-tabs
herdr plugin action invoke local.wrapped-tabs.refresh
```

A linked installation needs its source directory to remain available. The plugin restores the list on future Herdr server starts and adds it to new tabs and workspaces.

## Disable the plugin

Remove its panes and turn off automatic restoration:

```sh
herdr plugin action invoke local.wrapped-tabs.remove-all
herdr plugin disable local.wrapped-tabs
```

To turn it back on:

```sh
herdr plugin enable local.wrapped-tabs
herdr plugin action invoke local.wrapped-tabs.refresh
```

To hide it in just one workspace, run `herdr plugin action invoke local.wrapped-tabs.disable` while that workspace is active. Run `herdr plugin action invoke local.wrapped-tabs.enable` there to restore it.

Tabs with an existing multi-pane layout are left untouched: Herdr's plugin API cannot add a full-width row above an arbitrary layout without replacing running panes.
