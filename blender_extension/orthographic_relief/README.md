# Orthographic Relief

Orthographic Relief is a manual Blender extension that converts the active mesh
into a solid relief with no undercuts along a selected projection direction.

The extension performs four explicit steps when the user presses **Generate Relief**:

1. Capture the front-most surface as an orthographic depth image.
2. Convert depth to normalized height and apply Gaussian blur.
3. Rebuild the image as a single-valued height field on a closed base.
4. Add a Corrective Smooth modifier restricted to the relief surface.

**Base Shape** defaults to **Source Silhouette**. This trims the front, back,
and side wall to the projected outline of the source mesh, so an apple produces
an apple-shaped relief instead of an apple on a rectangular plaque. Choose
**Rectangle** to retain the original plaque output.

The longest-axis depth resolution can be set as high as 1024. Aspect fitting is
enabled by default so non-square sources retain full detail without generating a
needlessly square mesh. A silhouette solid needs front and back vertices, so a
fully occupied square image at resolution 1024 can approach 2.1 million vertices.
Resolution 512 is the recommended default.

## Use

1. Select a mesh object.
2. Open the 3D View sidebar with `N`.
3. Choose the **Relief** tab.
4. Set the projection and dimensions, then press **Generate Relief**.

`View From +Z` means looking from positive Z toward negative Z. `Camera` uses
the active scene camera orientation.

The undercut-free guarantee applies only along the selected projection direction.

## Live 3D preview

Press **Start Live Preview** to create a lightweight 3D relief, 128 samples by
default. Margin, Gaussian Blur, Depth Gamma, Minimum Height, and geometry settings
refresh automatically after a 0.2 second debounce. The source object is restored
when preview stops or the final relief is generated. Blur radius is scaled to
approximate the final resolution's world-space appearance.

## CAD / Rhino quad copy

Select a relief and press **Create Adaptive CAD Quad Copy** to bake its evaluated
modifiers and rebuild a lower-density, all-quad duplicate. The original object is
not changed.

**Adaptive Detail (ReQuad)** is the default backend when the separately installed
[ReQuad extension](https://github.com/mlstr0m/requad/releases/latest) is enabled.
It uses QuadWild bi-MDF, places smaller quads on curved detail, supports red/cyan
color-attribute density painting, and re-projects relaxed vertices to the source.
The bundled **Blender QuadriFlow** backend remains available without dependencies.

**Preserve Sharp Edges** is enabled by default. Sharp transitions around the
relief, side wall, and back may become intentional unwelded boundary seams. These
are accepted as valid output so Rhino `ToSubD` can convert them to crease edges
with `MeshCreases=Yes`. Disable **Preserve Sharp Edges** when a completely closed
manifold is more important than explicit SubD creases.

For STEP conversion, export the quad copy as OBJ, then use Rhino `ToSubD`,
`ToNURBS`, and STEP export. Do not use STL for this path because STL triangulates
the quad mesh.

## Privacy and connectivity

This extension has no MCP integration, network listener, telemetry, or background
service. Work starts only after the user starts Live Preview or presses a generate
button. The optional ReQuad backend launches ReQuad's separately installed local
engine and does not add network access. File permission is declared solely because
the optional PNG export writes depth images to disk.

## License

GPL-3.0-or-later.
