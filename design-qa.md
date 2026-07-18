# Sidebar navigation design QA

- Source visual truth: `C:\Users\gawk\AppData\Local\Temp\codex-clipboard-904e8297-f24b-4c33-9877-80a895aca3f7.png`
- Implementation screenshot: `C:\Users\gawk\.codex\visualizations\2026\07\15\019f6684-c12a-7081-b7e6-1582ecdf648e\invoice-export-sidebar-collapsed-fixed-v2.png`
- Viewport: 1920 x 1080, scale 1.0
- State: report/export page, collapsed 56 px navigation rail

## Full-view comparison evidence

The source showed two competing blue navigation signals: an outline around the
first item and a light-blue selected tile around the export item. The revised
capture shows only the export item as a light-blue rounded tile; all inactive
items are neutral and the page layout remains unchanged.

The synthetic fixture does not reproduce the user's report-group contents, so
content density outside the navigation rail was excluded from this scoped QA.

## Focused navigation comparison

- Typography: icon sizing and alignment remain consistent; no text is present
  in the collapsed rail.
- Spacing and layout rhythm: the rail remains 56 px wide and the selected tile
  preserves the existing 44 px item height and rounded geometry.
- Colors and tokens: the current page uses the existing selected surface and
  accent-border tokens; inactive entries no longer receive a competing blue
  focus outline in collapsed mode.
- Image and icon fidelity: the existing icon-provider assets are unchanged.
- Copy and content: no navigation labels or accessible names were changed.

## Findings and comparison history

1. P2, fixed: inactive first item retained a blue focus outline in the collapsed
   rail, creating a false double-selection state. Collapsed navigation now uses
   `Qt.NoFocus`; expanded navigation retains `Qt.TabFocus`.
2. P2, fixed: the previous current-page indicator used a left blue bar. The
   checked state now uses a shallow light-blue rounded block with a subtle
   accent border and no geometry-shifting left indicator.
3. Post-fix evidence: the 1920 x 1080 native capture reports a 56 px navigation
   width, zero clipping failures, zero warnings, and visibly one selected item.

No actionable P0, P1, or P2 navigation findings remain. No focused crop was
needed because the full-resolution comparison clearly resolves every 44 px rail
item and its border state.

final result: passed
