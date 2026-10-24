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

## Privacy and connectivity

This extension has no MCP integration, network listener, telemetry, or background
service. It runs only after a user presses the generate button. File permission is
declared solely because the optional PNG export writes depth images to disk.

## License

GPL-3.0-or-later.
