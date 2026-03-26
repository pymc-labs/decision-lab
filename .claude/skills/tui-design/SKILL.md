---
name: TUI Design System
description: Visual language and UX patterns for Textual TUI applications in dlab
---

# TUI Design System

Design decisions for all Textual TUI apps in this project. Follow these patterns when creating or modifying TUI screens.

## Theme & Layout

- **Theme**: `monokai` (set on App class: `theme = "monokai"`)
- **Screen alignment**: `align: left bottom` — content anchors to bottom-left, where terminal users look
- **Container width**: `width: 66%` — two-thirds of terminal
- **Container height**: `height: auto` — only as tall as content. Add `max-height: 80%` on `VerticalScroll` containers to preserve scrollability
- **No chrome**: Never use `Header()` or `Footer()` — the terminal stays dark above and to the right of the content

## Accent Blocks

Every interactive element gets a colored left border + surface background:

```css
Input {
    border: none;
    border-left: tall $accent;
    height: 1;
    padding: 0 1;
    background: $surface;
    &:focus { border: none; border-left: tall $accent; }
}
OptionList {
    border: none;
    border-left: tall $accent;
    background: $surface;
    scrollbar-size: 1 1;
}
```

Checkbox groups use a `.cb-group` wrapper with the same treatment:
```css
.cb-group {
    border-left: tall $accent;
    background: $surface;
    padding: 0 1;
}
```

## Checkboxes

Use `DpackCheckbox` (subclass of `Checkbox`) with custom glyphs:
- Unchecked: `▢`
- Checked: `▣`
- Override `BUTTON_LEFT = ""`, `BUTTON_RIGHT = ""`
- Override `_button` property to swap glyph based on `self.value`

CSS for visibility on dark backgrounds:
```css
Checkbox > .toggle--button { color: $text-muted; }
Checkbox.-on > .toggle--button { color: $success; }
```

## Navigation

### Arrow Keys
App-level bindings for field navigation:
```python
Binding("down", "focus_next", show=False),
Binding("up", "focus_previous", show=False),
Binding("left", "focus_previous", show=False),
Binding("right", "focus_next", show=False),
```
These only fire when the focused widget doesn't consume the key (Input consumes left/right for cursor, OptionList consumes up/down for selection).

### Tab Behavior
- **Normal widgets**: Tab moves to next focusable element (default Textual behavior)
- **Inside `.cb-group`**: Tab jumps OUT of the container to the next element outside. Implemented via `DpackCheckbox.action_tab_out()` which walks ancestors to find the `.cb-group` parent, then focuses the first widget after it in `screen.focus_chain`
- **Selection widgets**: Show "Tab to continue" hint via `:focus-within`:
```css
.option-hint { display: none; color: $text-muted; text-style: italic; height: 1; }
.selection-group:focus-within .option-hint { display: block; }
```

### Button Order
- **Primary action first in DOM** (focus order): Next, Create, etc.
- **Visually on the right** via `dock: right`:
```css
#next-btn, #create-btn, #done-btn, #skip-btn, #keep-btn { dock: right; }
```
- Back button stays in normal flow (left side)
- Nav-bar: `Horizontal(classes="nav-bar")` with `height: 1`

### OptionList Selection
When user selects an item in an OptionList (e.g. package manager), auto-advance focus to the next element via `on_option_list_option_selected` → `self.screen.focus_next()`.

## Typography

- **Step indicator**: `[b]Step N of M[/b] — Title` as `.field-label`
- **Field labels**: `.field-label` with `margin-top: 1`
- **Descriptions/hints**: `.field-hint` and `.cb-desc` with `color: $text-muted; text-style: italic`
- **Errors**: `.error-label` with `color: $error`
- **Section dividers**: `.section-divider` with `color: $accent`

## Buttons

```css
Button {
    min-width: 10;
    border: none;
    background: $surface;
    &:hover { background: $primary; }
    &.-success { background: $success-muted; &:hover { background: $success; } }
}
```
All variants have `border: none`. No special styling for `-primary` variant (buttons look uniform).

## Collision Detection Pattern

When user input might conflict with existing state (e.g. decision-pack name already exists):
1. Show red error label
2. Show a "Delete & Overwrite" button (`variant="error"`, with `color: $text` CSS override for visibility)
3. Place both in a `Horizontal(id="collision-bar")` so they sit side by side
4. On overwrite click: set state flag, show green confirmation, hide button
5. Reset on input change

## Creation Flow Pattern

For long-running operations (e.g. generating files, downloading):
1. Run in `@work(thread=True)` method
2. Accept `on_progress: Callable[[str], None]` callback
3. Update UI via `app.call_from_thread(label.update, message)`
4. On success: show walkthrough/results
5. On error: show error + recovery options (Go Back, Keep Partial, Abort)

## Color Palette (Connect TUI)

Uses monokai hex colors for consistency:

| Role | Color | Hex |
|------|-------|-----|
| Process start | monokai cyan | `#66D9EF` |
| Completion | monokai green | `#A6E22E` |
| Action/tool | monokai orange | `#FD971F` |
| Error | monokai red | `bold #F92672` |
| Selection/identity | monokai purple | `#AE81FF` |
| Background info | monokai comment | `#75715E` |
| Main text | monokai foreground | `#F8F8F2` |
