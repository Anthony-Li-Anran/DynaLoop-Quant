# DynaLoop Quant UI

Live catalog: /components. All catalog records are explicitly labeled demonstration data.

## Layers
- Foundations: ../styles/index.css owns palette, spacing, radii and typography. ../app/brand.ts owns the product identity.
- Primitives: ui/Button, ui/Badge.
- Shared patterns: shared/PageHeader, Panel, MetricCard, DataTable, MetadataList, StatusBadge, QueryState and formatting helpers.
- Domain components: ../features/data/components, ../features/experiments/components, ../features/runtime/components.
- Pages compose components and obtain data through API/query hooks.

## Composition
Use Panel for titled content. DetailPanel is a compatibility alias of Panel, not another implementation.
Use PageHeader for every page title and SectionHeader for section headings.
Use MetricCard for metrics (card or strip), StatusBadge for states, DataTable for tabular records.
DataTable has typed columns, stable row keys and optional keyboard-accessible selection.
Keep shared components independent of API calls and domain data.

## Visual conventions
Fixed Modern Research typography: Segoe UI with system/Chinese sans-serif fallbacks for headings and prose; Consolas with monospace fallbacks for identifiers and numeric values. Page titles use 26px, 1.4 line height, weight 600 and 0.005em tracking. Font tokens live only in styles/index.css; there is no runtime font selector or stored typography preference.
Neutral dark surfaces, restrained gold brand accents, semantic status colors.
Use the 4/8/12/16/24 spacing scale. Do not redefine panel, heading or table styles inside pages.
Display unavailable values distinctly from zero. Never populate product pages with catalog fixtures.

## Adding a component
First check existing shared and domain components. Add only a pattern needed by the product.
Define TypeScript props and loading/empty/error behavior where relevant.
Add a working example to ComponentsPage for reusable shared components.
Test meaningful interactions and accessibility; run npm test and npm run build.
