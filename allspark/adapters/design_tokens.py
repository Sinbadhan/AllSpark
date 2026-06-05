"""AllSpark Tactical Terminal Design Tokens.

Extracted from Stitch design system. Used by templates for consistent theming.
"""

# Tailwind CSS color tokens (from Stitch DESIGN.md)
COLORS = {
    # Surface
    "background": "#131313",
    "surface": "#131313",
    "surface_dim": "#131313",
    "surface_bright": "#393939",
    "surface_container_lowest": "#0e0e0e",
    "surface_container_low": "#1b1c1c",
    "surface_container": "#1f2020",
    "surface_container_high": "#2a2a2a",
    "surface_container_highest": "#353535",

    # Primary (Spark Orange)
    "primary": "#ffb59d",
    "primary_container": "#ff6b35",
    "on_primary": "#5d1900",
    "on_primary_container": "#5f1900",
    "primary_fixed": "#ffdbd0",
    "primary_fixed_dim": "#ffb59d",
    "on_primary_fixed": "#390c00",
    "on_primary_fixed_variant": "#832600",
    "inverse_primary": "#ab3500",

    # Secondary (Charcoal)
    "secondary": "#c8c6c5",
    "secondary_container": "#4a4949",
    "on_secondary": "#313030",
    "on_secondary_container": "#bab8b7",
    "secondary_fixed": "#e5e2e1",
    "secondary_fixed_dim": "#c8c6c5",
    "on_secondary_fixed": "#1c1b1b",
    "on_secondary_fixed_variant": "#474646",

    # Tertiary (Command Purple)
    "tertiary": "#dfb7ff",
    "tertiary_container": "#c079ff",
    "on_tertiary": "#4b007e",
    "on_tertiary_container": "#4d0081",
    "tertiary_fixed": "#f1daff",
    "tertiary_fixed_dim": "#dfb7ff",
    "on_tertiary_fixed": "#2d004f",
    "on_tertiary_fixed_variant": "#6a00b0",

    # Error
    "error": "#ffb4ab",
    "error_container": "#93000a",
    "on_error": "#690005",
    "on_error_container": "#ffdad6",

    # Text
    "on_surface": "#e4e2e1",
    "on_surface_variant": "#e1bfb5",
    "on_background": "#e4e2e1",
    "inverse_surface": "#e4e2e1",
    "inverse_on_surface": "#303030",

    # Outline
    "outline": "#a98a80",
    "outline_variant": "#594139",
    "surface_tint": "#ffb59d",
    "surface_variant": "#353535",

    # AllSpark-specific overrides (from project_rules.md)
    "bg": "#0a0a0a",
    "card": "#141414",
    "border": "#2a2a2a",
    "text": "#e0e0e0",
    "dim": "#666",
    "accent": "#ff6b35",
    "critical": "#ff4444",
    "warning": "#ffaa00",
    "success": "#44cc44",
    "info": "#4488ff",
}

# Typography
TYPOGRAPHY = {
    "font_family": "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
    "display_lg": {"size": "24px", "weight": "700", "line_height": "32px", "letter_spacing": "-0.01em"},
    "headline_md": {"size": "18px", "weight": "600", "line_height": "24px", "letter_spacing": "0"},
    "body_base": {"size": "14px", "weight": "400", "line_height": "21px", "letter_spacing": "0"},
    "body_bold": {"size": "14px", "weight": "600", "line_height": "21px", "letter_spacing": "0"},
    "label_caps": {"size": "11px", "weight": "600", "line_height": "16px", "letter_spacing": "0.05em"},
    "stat_lg": {"size": "20px", "weight": "700", "line_height": "28px", "letter_spacing": "0"},
}

# Border Radius
RADIUS = {
    "sm": "2px",
    "default": "4px",
    "md": "6px",
    "lg": "8px",
    "xl": "12px",
    "full": "9999px",
}

# Spacing (4px baseline)
SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "24px",
    "xxl": "32px",
    "gutter": "12px",
}

# Tailwind config JSON (for CDN script tag)
TAILWIND_CONFIG = {
    "darkMode": "class",
    "theme": {
        "extend": {
            "colors": {
                "surface": "#131313",
                "surface-dim": "#131313",
                "surface-bright": "#393939",
                "surface-container-lowest": "#0e0e0e",
                "surface-container-low": "#1b1c1c",
                "surface-container": "#1f2020",
                "surface-container-high": "#2a2a2a",
                "surface-container-highest": "#353535",
                "primary": "#ffb59d",
                "primary-container": "#ff6b35",
                "on-primary": "#5d1900",
                "on-primary-container": "#5f1900",
                "secondary": "#c8c6c5",
                "secondary-container": "#4a4949",
                "on-secondary": "#313030",
                "on-secondary-container": "#bab8b7",
                "tertiary": "#dfb7ff",
                "tertiary-container": "#c079ff",
                "on-tertiary": "#4b007e",
                "on-tertiary-container": "#4d0081",
                "error": "#ffb4ab",
                "error-container": "#93000a",
                "on-error": "#690005",
                "on-surface": "#e4e2e1",
                "on-surface-variant": "#e1bfb5",
                "on-background": "#e4e2e1",
                "outline": "#a98a80",
                "outline-variant": "#594139",
                "surface-tint": "#ffb59d",
                "surface-variant": "#353535",
                "inverse-surface": "#e4e2e1",
                "inverse-on-surface": "#303030",
                "inverse-primary": "#ab3500",
                "background": "#131313",
            },
            "borderRadius": {
                "DEFAULT": "4px",
                "lg": "8px",
                "xl": "12px",
                "full": "9999px",
            },
            "fontFamily": {
                "mono": ["JetBrains Mono", "Fira Code", "SF Mono", "monospace"],
            },
        },
    },
}
