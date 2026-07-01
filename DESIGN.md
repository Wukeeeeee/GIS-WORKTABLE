---
name: Monolith GIS
colors:
  surface: '#fdf8f8'
  surface-dim: '#ddd9d8'
  surface-bright: '#fdf8f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f7f3f2'
  surface-container: '#f1edec'
  surface-container-high: '#ebe7e6'
  surface-container-highest: '#e5e2e1'
  on-surface: '#1c1b1b'
  on-surface-variant: '#444748'
  inverse-surface: '#313030'
  inverse-on-surface: '#f4f0ef'
  outline: '#747878'
  outline-variant: '#c4c7c7'
  surface-tint: '#5f5e5e'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1c1b1b'
  on-primary-container: '#858383'
  inverse-primary: '#c8c6c5'
  secondary: '#5d5f5f'
  on-secondary: '#ffffff'
  secondary-container: '#dddddd'
  on-secondary-container: '#606161'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#1c1b1a'
  on-tertiary-container: '#868382'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e5e2e1'
  primary-fixed-dim: '#c8c6c5'
  on-primary-fixed: '#1c1b1b'
  on-primary-fixed-variant: '#474746'
  secondary-fixed: '#e2e2e2'
  secondary-fixed-dim: '#c6c6c6'
  on-secondary-fixed: '#1a1c1c'
  on-secondary-fixed-variant: '#454747'
  tertiary-fixed: '#e6e2df'
  tertiary-fixed-dim: '#cac6c4'
  on-tertiary-fixed: '#1c1b1a'
  on-tertiary-fixed-variant: '#484645'
  background: '#fdf8f8'
  on-background: '#1c1b1b'
  surface-variant: '#e5e2e1'
  ui-white: '#FFFFFF'
  ui-gray-50: '#F8F8F8'
  ui-gray-100: '#EAEAEA'
  ui-gray-200: '#D1D1D1'
  ui-gray-300: '#888888'
  ui-gray-400: '#444444'
  ui-gray-900: '#1A1A1A'
typography:
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-sm:
    fontFamily: Hanken Grotesk
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  panel-width-chat: 320px
  panel-height-bottom: 240px
  gutter: 1px
  margin-sm: 8px
  margin-md: 16px
  stack-gap: 4px
---

## Brand & Style
The brand personality is anchored in **Minimalism** and **High-Utility Professionalism**. This design system is built specifically for GIS professionals who require zero visual interference from the interface while interpreting complex geospatial data. 

The aesthetic is "Systematic Grayscale," utilizing a monochrome palette to ensure that the only colors present on the screen are the data layers themselves. The interface feels like a high-precision tool—utilitarian, reliable, and invisible. It draws from **Brutalist** influences through its clear divisions and structural lines, but maintains a **Corporate Modern** level of refinement through precise spacing and sophisticated typography.

## Colors
This design system employs a strict grayscale monochrome palette. The absence of color is a functional choice to prevent UI elements from competing with geospatial symbology.

- **Primary Canvas**: The map area uses `ui-white` or `ui-gray-50` as its base.
- **Surface & Panels**: Side and bottom panels use `ui-gray-100` to create a distinct structural container around the map.
- **Borders & Dividers**: `ui-gray-200` is the workhorse for component outlines and panel separators.
- **Typography**: Functional text is set in `ui-gray-900` for maximum legibility, while `ui-gray-400` is reserved for secondary metadata and placeholders.

## Typography
The typography is selected for data-heavy professional use, emphasizing clarity and information density.

- **Headlines**: Hanken Grotesk provides a sharp, contemporary look for panel titles and major headers.
- **Body**: Inter is used for chat messages and general UI text due to its exceptional legibility at small sizes.
- **Labels/Data**: JetBrains Mono is used for layer filenames, coordinates, and technical attributes to signify "data" status and ensure character distinction (e.g., distinguishing '0' from 'O').

## Layout & Spacing
The layout follows a "Fixed-Dock" philosophy optimized for large displays.

1. **Map Canvas**: A fluid central area that expands to all available space not occupied by panels.
2. **Chat Panel (Left)**: A fixed 320px sidebar for AI interaction.
3. **Utility Dock (Bottom)**: A horizontal panel divided into "Layer Management" and "File Operations."

Spacing is tight and systematic. A **1px gutter** (the border width) is used between panels to create a seamless, tiled appearance. Internal padding for components uses a 4px baseline to maintain high information density suitable for GIS workflows.

## Elevation & Depth
This design system avoids shadows to maintain a flat, professional "blueprint" aesthetic. Depth is communicated through **Tonal Layering** and **Line Work**:

- **Level 0 (Background)**: `ui-gray-100` for the outer application shell and panel backgrounds.
- **Level 1 (Interactive Surfaces)**: `ui-white` for map canvas, chat bubbles, and active input fields.
- **Level 2 (Feedback)**: `ui-gray-200` for hover states and selection highlights.

Borders are strictly 1px wide using `ui-gray-200`. Inactive or disabled states are communicated through `ui-gray-300` fills rather than transparency.

## Shapes
Shapes are "Soft" but lean toward "Sharp." A minimal **0.25rem (4px)** radius is applied to buttons, input fields, and chat bubbles to provide just enough visual comfort without compromising the professional, grid-based layout. Panel corners that meet the edge of the browser window remain at 0px.

## Components

### Buttons
- **Primary**: `ui-gray-900` background with `ui-white` text. No roundedness beyond 4px.
- **Secondary**: `ui-white` background with `ui-gray-200` border and `ui-gray-900` text.
- **Action Icons**: 24x24px hit area, `ui-gray-400` icon color, switching to `ui-gray-900` on hover.

### Chat Bubbles
- **User**: Minimal border `ui-gray-200`, `ui-white` background, aligned right.
- **AI**: `ui-gray-50` background, no border, aligned left. Use `label-mono` for any coordinate or code outputs.

### Input Fields
- Flat `ui-white` background with a `ui-gray-200` bottom border only (or full border for chat input). 
- Placeholder text in `ui-gray-400`.

### Layer List Items
- Height-constrained rows (32px) with `ui-gray-200` bottom borders.
- Include "visibility" (eye) and "delete" (trash) icons that appear on row hover.
- Use `label-mono` for file extensions like `.shp` or `.geojson`.

### Cards & Panels
- Panels do not use shadows. They are separated by 1px solid `ui-gray-200` lines.
- The "Layer Manager" and "New File" sections are clearly demarcated by vertical 1px rules.