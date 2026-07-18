# Invoice Hub Design System v1.1 — Visual Language

## Product character

Invoice Hub is a quiet, trustworthy and compact personal reimbursement workspace. Visual emphasis comes from hierarchy, spacing and filled interaction states rather than decorative outlines.

## Two page archetypes

1. **StandardPage** — 今日工作台、导入中心、报销组与导出、系统设置。
   - shared left-aligned `PageHeader`
   - centered maximum-width content
   - 24px page margin and 16px section gap
2. **WorkbenchPage** — 发票审核。
   - full-width dense task surface
   - no decorative page title
   - table, preview and detail panel remain primary

## Interaction semantics

### Navigation

- normal: transparent surface, secondary text
- hover: subtle surface, primary text
- selected: blue selected fill, accent text, no decorative border
- keyboard focus: visible fill and accent text, no Windows-native outline
- collapse control: navigation footer control, not a secondary action button; transparent by default and borderless in every state

### Review status filter

The five states form a single `SegmentedFilter`:

- one shared neutral container
- individual segments have no independent border
- active segment uses the selected blue surface
- status colors are reserved for invoice badges and validation messages, not navigation/filter chrome

This separates two different meanings:

- **selection** → accent blue
- **business status** → success / warning / danger badges

### Cards

Cards represent content containment, not every clickable element.

- background: `surface`
- border: `border`
- radius: `radius_large`
- do not wrap navigation controls or status filters in card-like colored outlines

## Authoritative mapping

| Figma concept | Qt contract |
|---|---|
| `Color/Surface/Page` | `DESIGN_V1_COLORS['page']` |
| `Color/Surface/Primary` | `DESIGN_V1_COLORS['surface']` |
| `Color/Surface/Selected` | `DESIGN_V1_COLORS['selected']` |
| `Color/Text/Primary` | `DESIGN_V1_COLORS['text']` |
| `Color/Text/Secondary` | `DESIGN_V1_COLORS['text_secondary']` |
| `Color/Accent/Primary` | `DESIGN_V1_COLORS['accent']` |
| `Radius/Control` | `DESIGN_V1_METRICS['radius_medium']` |
| `Control/IconButton` | `DESIGN_V1_METRICS['icon_button_size']` |
| `Control/Segmented` | `DESIGN_V1_METRICS['segmented_control_height']` |
| `Control/Segment` | `DESIGN_V1_METRICS['segmented_item_height']` |

## Review acceptance

At Windows 100%, 125% and 150% scaling:

- sidebar collapse control has no button outline
- selected main navigation has a single filled state and no border
- status filter appears as one segmented control
- unselected status segments have no colored border
- the selected segment remains clearly visible
- status badges in the invoice table retain semantic colors
- keyboard operation remains available without native dotted or black focus rectangles
