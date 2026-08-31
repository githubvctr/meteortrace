# Coordinate Conventions

This document defines the spherical-geometry conventions used throughout
MeteorTrace's current geometry layer (`meteortrace.contracts`,
`meteortrace.geometry`). Later pipeline stages (pixel/WCS astrometry,
brightness, colour) will build on top of these conventions without
changing them.

## Physical object

A `CelestialCoordinate` represents a direction on the celestial sphere in
an ICRS-like spherical system: right ascension (`ra_deg`) and declination
(`dec_deg`), both in degrees. "ICRS-like" is used deliberately: this
initial layer performs no frame transformation, proper-motion correction,
or epoch handling. It treats RA/Dec pairs as points on the unit sphere.

## Units and ranges

- `ra_deg` is in degrees and is normalized to `[0, 360)` on construction.
  Values outside this range (including negative values) are wrapped, not
  rejected, because right ascension is inherently cyclic.
- `dec_deg` is in degrees and must lie in `[-90, 90]`. Values outside this
  range are physically meaningless and raise `ValueError`.
- Any plain `float` that represents an angle and crosses a public function
  boundary is named with a `_deg` suffix. Internally, `numpy.radians` /
  `numpy.degrees` perform the only unit conversions; radians and degrees
  are never mixed silently.

## Cartesian unit vectors

Each coordinate maps to a 3D unit vector via

$$
\mathbf{u}(\alpha, \delta) = (\cos\delta\cos\alpha,\ \cos\delta\sin\alpha,\ \sin\delta)
$$

where $\alpha$ is right ascension and $\delta$ is declination, both in
radians internally. This is the standard spherical-to-Cartesian mapping
for a unit celestial sphere; `+z` corresponds to the north celestial pole
in this ICRS-like frame.

## Angular separation

Separation between two coordinates is computed as

$$
\theta = \operatorname{atan2}\left(\lVert \mathbf{a}\times\mathbf{b}\rVert,\ \mathbf{a}\cdot\mathbf{b}\right)
$$

rather than $\arccos(\mathbf{a}\cdot\mathbf{b})$. The `arccos` form loses
precision catastrophically for separations near 0° and near 180°, because
its derivative diverges there. The `atan2` form remains numerically
well-conditioned across the full `[0°, 180°]` range.

## Ordered trails and orientation

An `ObservedTrail` is ordered from its visually earlier endpoint
(`start`) to its visually later endpoint (`end`). This order is a
scientific input, not an artifact of storage: it defines what "forward"
and "backward" mean everywhere downstream.

The great circle containing a trail has an oriented unit normal

$$
\hat{\mathbf{n}} = \frac{\mathbf{u}_{\text{start}} \times \mathbf{u}_{\text{end}}}{\lVert \mathbf{u}_{\text{start}} \times \mathbf{u}_{\text{end}} \rVert}
$$

which encodes the start→end direction, not merely the undirected circle.
"Backward" means the extension of the great circle opposite the observed
start→end motion; a genuine shower radiant is expected to lie on this
backward extension, since meteors appear to radiate away from it.

## Numerical degeneracies

A unique great circle requires two distinct, non-antipodal points. This
package rejects trails whose endpoint separation is below
$10^{-6}$° (effectively coincident) or above $180° - 10^{-6}$°
(effectively antipodal), raising `ValueError` in both cases. This
tolerance is expressed in angular terms (via the same stable `atan2`
separation formula) rather than as a raw vector-norm threshold, so it
behaves consistently near both degeneracies.

Similarly, projecting a radiant onto a great circle is undefined when the
radiant coincides with the circle's pole (a cross-track separation of
exactly 90°); this is also raised as an explicit `ValueError` rather than
silently returning an arbitrary point.

## Classification limitations

`radiant_cross_track_separation_deg` and `classify_radiant_alignment`
describe **geometric consistency** between a trail's great circle and a
candidate radiant: how close the alignment is, and whether it falls on
the physically expected backward extension. Neither function establishes
**shower membership**. Confirming membership requires velocity, timing,
and orbital information well beyond a single still trail's geometry, and
is out of scope for this layer.
