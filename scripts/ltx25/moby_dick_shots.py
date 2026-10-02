#!/usr/bin/env python3
"""Moby-Dick — Loomings: 22 sahnenin ShotSpec dönüşümü (kalite korumalı).

`projects/moby_dick_pilot/adaptation.yaml` içindeki her `motion_prompt` serbest
İngilizce metindi ve yeni şablona UYMUYORDU (sahne başına 6-8 ihlal). Burada her
sahne, `cinematic_prompt.ShotSpec` alanlarına yeniden yazılmıştır:

  shot_type → subject → action → environment → lighting → camera_move →
  direction → stillness → blocking → style → audio

Dönüşüm kuralı: olay özeti KORUNUR, yalnızca (a) iç duygu adları fiziksel
duruma çevrilir, (b) kamera dili tek ve gerçek bir harekete indirgenir (orbit /
yumuşak süzülme yerine dolly/track/crane — ilk render denemesindeki hata),
(c) yön kilidi (R-EXPLICIT-DIRECTION) yazılır, (d) negatif alan/hareketsizlik
(stillness) açıkça verilir, (e) ses ipucu sahneden türetilir.

Diyalog yoktur: anlatım `narration.faithful` post-production VO'sudur ve
prompt'a GİRMEZ (R-NO-VOICEOVER).

Kullanım
--------
    from moby_dick_shots import SCENE_SHOTS, shot_for_scene_id
    from cinematic_prompt import render_motion_prompt, validate_motion_prompt

    prompt = render_motion_prompt(shot_for_scene_id("call_me_ishmael"))
    assert validate_motion_prompt(prompt) == []
"""
from __future__ import annotations

from cinematic_prompt import ShotSpec

__all__ = [
    "SCENE_SHOTS",
    "SCENE_IDS",
    "shot_for_scene_id",
    "DEFAULT_STYLE",
]

#: Tüm sahnelerde paylaşılan görsel dil (post-production grade ile uyumlu).
DEFAULT_STYLE = (
    "Photorealistic historical drama, 35mm film grain, muted desaturated palette"
)

# ---------------------------------------------------------------------------
# Sahne 1-22. Anahtar: adaptation.yaml `scenes[].id` (birebir aynı).
# ---------------------------------------------------------------------------

SCENE_SHOTS: dict[str, ShotSpec] = {

    # 001_street.png -> 002_coffin.png
    "call_me_ishmael": ShotSpec(
        shot_type="medium",
        lens="35mm",
        subject=(
            "Ishmael, a weathered man in his early thirties in a charcoal greatcoat, "
            "collar up against the rain"
        ),
        action=(
            "walks slowly down the wet cobblestone street toward the harbour, "
            "head down and shoulders in tight against the rain"
        ),
        environment="a 1840s lower Manhattan street in fine November rain",
        lighting="cold overcast dawn with gas lamps lit along the kerb",
        camera_move="steadicam",
        direction=(
            "Ishmael walks screen left to screen right and keeps walking in that "
            "same direction for the whole shot"
        ),
        stillness="his hands stay inside his coat pockets, no visible gesture",
        style=DEFAULT_STYLE,
        audio="rain on cobblestones, distant carriage wheels, faint harbour wind, no dialogue",
    ),

    # 002_coffin.png -> 003_harbor_choice.png
    "november_in_the_soul": ShotSpec(
        shot_type="medium_close_up",
        lens="85mm",
        subject=(
            "Ishmael, a weathered man in his early thirties in a charcoal greatcoat, "
            "water beading on the wool"
        ),
        action=(
            "stands beneath dripping eaves and breathes out slow visible breath, "
            "jaw set and eyes down"
        ),
        environment="a 1840s coffin-warehouse frontage in a cold drizzly dawn",
        lighting="flat cold gray overcast light with a weak lamp glow behind him",
        camera_move="dolly_in",
        direction=(
            "Ishmael stays in place at screen left while a funeral cart rolls past "
            "him in soft focus from screen right to screen left"
        ),
        stillness="his shoulders stay set and his hands remain inside his coat",
        style=DEFAULT_STYLE,
        audio="drip from the eaves, low wheels on wet stone, no dialogue",
    ),

    # 003_harbor_choice.png -> 004_manhattan.png
    "substitute_for_pistol": ShotSpec(
        shot_type="medium",
        lens="35mm",
        subject=(
            "Ishmael, a weathered man in his early thirties in a charcoal greatcoat, "
            "chin lifting"
        ),
        action=(
            "walks on to the end of the street and stops at the harbour rail as ship "
            "rigging shows through the rain"
        ),
        environment="a street of wet stone meeting a working harbour quay in fine rain",
        lighting="cold gray dawn with a break of pale light low over the water",
        camera_move="dolly_out",
        direction=(
            "Ishmael moves away from the camera toward the open water and then holds "
            "his ground facing forward"
        ),
        stillness="both hands rest on the rail, his coat stills when he stops",
        style=DEFAULT_STYLE,
        audio="rain, rope and block noise from a hull tied at the quay, harbour wind, no dialogue",
    ),

    # 004_manhattan.png -> 005_sentinels.png
    "insular_city": ShotSpec(
        shot_type="extreme_wide",
        lens="24mm",
        subject=(
            "the island of Manhattan with timber wharves and sailing ships at "
            "anchor, the whole town small in frame"
        ),
        action="sits still while the streets on both sides run down to the water",
        environment="a full aerial view over an 1840s harbour city and its surrounding bay",
        lighting="flat gray daylight under a low overcast sky",
        camera_move="crane_up",
        direction=(
            "the camera rises and drifts forward so the shoreline slides downward "
            "across frame toward the bottom edge"
        ),
        stillness="no close figure enters the foreground, the town keeps a steady outline",
        style=DEFAULT_STYLE,
        audio="bay water, distant gulls, faint dock noise, no dialogue",
    ),

    # 005_sentinels.png -> 006_landsmen.png
    "silent_sentinels": ShotSpec(
        shot_type="wide",
        lens="50mm",
        subject=(
            "rows of men in dark period coats standing along the Battery piers at the "
            "water edge"
        ),
        action=(
            "stand leaning on the pilings and stare seaward while their coat hems stir "
            "in the salt breeze"
        ),
        environment="the Battery piers on a quiet Sabbath afternoon in 1840s New York",
        lighting="soft hazy daylight with thin sun behind haze",
        camera_move="track_left",
        direction=(
            "the men keep facing the open water as the camera slides left along the "
            "line of pilings"
        ),
        stillness="their feet stay firm on the planks, only coats and hat ribbons move",
        style=DEFAULT_STYLE,
        audio="small waves against timber, gulls, breeze in canvas, no dialogue",
    ),

    # 006_landsmen.png -> 007_edge.png
    "landsmen_at_the_edge": ShotSpec(
        shot_type="medium_wide",
        lens="35mm",
        subject=(
            "a line of landsmen in worn period coats and sleeves up past the elbow, hands and "
            "elbows worn from shop work"
        ),
        action=(
            "walk out from the lane onto the timber pier and stop at the outer rail, "
            "hands laid on the top rail"
        ),
        environment="a timber pier at the end of a narrow 1840s Manhattan street",
        lighting="low hazy afternoon sun with weak reflections off the wet planks",
        camera_move="dolly_in",
        direction=(
            "the line of men walks forward toward the water and then holds at the rail "
            "facing out"
        ),
        stillness="after they reach the rail their weight stays even on both feet",
        style=DEFAULT_STYLE,
        audio="boots on hollow planks, harbour water, rigging hum, no dialogue",
    ),

    # 007_edge.png -> 008_compass.png
    "extremest_limit": ShotSpec(
        shot_type="wide",
        lens="35mm",
        subject=(
            "a stream of walkers in 1840s coats pouring out of narrow lanes toward the "
            "Battery"
        ),
        action=(
            "walk straight for the water and stop in a line at the last safe plank "
            "above the tide, then go still"
        ),
        environment="a narrowing Battery headland ending in bare planks above the tide",
        lighting="flat gray daylight with a thin band of sun at the horizon",
        camera_move="dolly_in",
        direction=(
            "every walker moves forward toward the waterline and halts at the plank "
            "edge, none turns back"
        ),
        stillness="at the plank edge the whole line stops moving at once, coats only",
        style=DEFAULT_STYLE,
        audio="many feet on boards, surf below, gull calls, no dialogue",
    ),

    # 008_compass.png -> 009_country.png
    "magnetic_water": ShotSpec(
        shot_type="medium",
        lens="50mm",
        subject=(
            "Ishmael, a man in his early thirties in a charcoal greatcoat, shown from "
            "behind between a brass compass and taut rigging lines"
        ),
        action="stands at the rail and turns his head slowly toward the horizon",
        environment="the rail of a packet ship tied at the quay facing the open harbour",
        lighting="cold gray daylight with a bright strip of water beyond the rail",
        camera_move="dolly_in",
        direction=(
            "Ishmael keeps his back to the camera, his body stays forward toward the horizon "
            "at the right of frame and his gaze does not leave it"
        ),
        stillness="his feet stay firm on the deck and the rigging lines keep their tension",
        style=DEFAULT_STYLE,
        audio="rigging hum, halyard clank, harbour water, no dialogue",
    ),

    # 009_country.png -> 010_reflection.png
    "path_to_water": ShotSpec(
        shot_type="extreme_wide",
        lens="24mm",
        subject=(
            "a single traveller in a plain travelling coat on a winding path through "
            "green high country"
        ),
        action=(
            "walks downhill step by step until the path levels out beside a still pool "
            "in the stream"
        ),
        environment="a green dale descending from high hills to a deep pool in a live stream",
        lighting="clear afternoon sun through leaves, cool shade in the trees",
        camera_move="tilt_down",
        direction=(
            "the traveller moves from the top of frame down the path toward the water "
            "at the bottom of frame"
        ),
        stillness="the pool surface stays unbroken except for leaves landing on it",
        style=DEFAULT_STYLE,
        audio="stream over stones, light leaves, distant birds, no dialogue",
    ),

    # 010_reflection.png -> 011_saco.png
    "meditation_and_water": ShotSpec(
        shot_type="medium",
        lens="50mm",
        subject=(
            "a lone traveller in a plain travelling coat standing at the bank of a "
            "shallow stream"
        ),
        action=(
            "stops walking and looks down as his reflection spreads into rings and drifts "
            "apart on the moving water"
        ),
        environment="the bank of a slow stream in open country under low trees",
        lighting="soft even daylight with no hard shadow, pale bounce light off the water",
        camera_move="rack_focus",
        direction=(
            "the traveller stays at the bank while focus travels from his still "
            "figure forward onto the water moving past him"
        ),
        stillness="his hands hang loose at his sides and he does not shift his weight",
        style=DEFAULT_STYLE,
        audio="stream surface, faint wind in grass, distant birds, no dialogue",
    ),

    # 011_saco.png -> 012_prairie.png
    "magic_stream": ShotSpec(
        shot_type="extreme_wide",
        lens="24mm",
        subject=(
            "a painter in a plain coat standing on a rise above a wide valley of meadow, "
            "cattle, cottage smoke, pines and blue mountain spurs"
        ),
        action="stands still and lowers his gaze to one bright winding stream in the valley floor",
        environment="a broad nineteenth-century valley in the Saco country under open sky",
        lighting="clear mid-morning sun with long soft shadow across the meadow",
        camera_move="pan_right",
        direction=(
            "the painter stands still on the rise while the camera pans right along the "
            "valley toward the bright stream on the far side"
        ),
        stillness="he holds his ground with his sketch hand down, only the grass stirs",
        style=DEFAULT_STYLE,
        audio="wind across grass, distant cattle, stream chatter, no dialogue",
    ),

    # 012_prairie.png -> 013_narcissus.png
    "the_missing_charm": ShotSpec(
        shot_type="wide",
        lens="35mm",
        subject=(
            "a vast June prairie underfoot with tiger lilies and dry bunch grass to the "
            "horizon"
        ),
        action="sways in waves as the dry wind crosses it, petals shaking loose from the stems",
        environment="open flat prairie land in June with no water anywhere in sight",
        lighting="high harsh midday sun with hard short shadow under the stems",
        camera_move="dolly_in",
        direction=(
            "the wind travels left to right across the field and the camera pushes "
            "forward into it in the same direction"
        ),
        stillness="the far horizon line stays level and unbroken, nothing rises from it",
        style=DEFAULT_STYLE,
        audio="dry grass hiss, insects, open wind with no water sound, no dialogue",
    ),

    # 013_narcissus.png -> 014_quay.png
    "phantom_of_life": ShotSpec(
        shot_type="medium_close_up",
        lens="85mm",
        subject=(
            "Narcissus, a youth in a classical drapery, kneeling at the rim "
            "of a dark forest pool"
        ),
        action=(
            "kneels and reaches one hand toward the water as his reflection breaks into "
            "rings and spreads out to the far bank"
        ),
        environment="a forest pool with a low bank of moss and ferns",
        lighting="low warm light through trees with deep shade across the water",
        camera_move="crane_up",
        direction=(
            "the camera rises from the kneeling figure to a higher angle over the pool, "
            "moving upward and slightly forward"
        ),
        stillness="his knees stay on the bank and his hand stops just above the surface",
        style=DEFAULT_STYLE,
        audio="water lapping at the bank, leaves overhead, distant birds, no dialogue",
    ),

    # 014_quay.png -> 015_forecastle.png
    "never_a_passenger": ShotSpec(
        shot_type="medium_wide",
        lens="35mm",
        subject=(
            "Ishmael, a man in his early thirties in a charcoal greatcoat, and a "
            "passenger in a fine travelling cloak at the quay trunk pile"
        ),
        action=(
            "walks past the paying group and turns his body toward the working "
            "forecastle of a merchant vessel lying alongside"
        ),
        environment="a busy 1840s packet-ship quay with trunks, crates and hulls at anchor",
        lighting="cold gray overcast daylight off the harbour water",
        camera_move="track_right",
        direction=(
            "Ishmael walks screen left to screen right away from the quay office and "
            "toward the ship's hull at the right of frame"
        ),
        blocking=(
            "the passenger stays at the trunk pile 6 m from Ishmael while Ishmael "
            "crosses to the hull ladder"
        ),
        stillness="the porter keeps his hands on the trunk straps while Ishmael passes",
        style=DEFAULT_STYLE,
        audio="quay shouting, crate thud, hull creak, harbour wind, no dialogue",
    ),

    # 015_forecastle.png -> 016_sweeping.png
    "before_the_mast": ShotSpec(
        shot_type="medium_wide",
        lens="24mm",
        subject=(
            "Ishmael, a man in a plain work shirt, hauling a coil of "
            "coarse rope on the foredeck beside a sailor in oilskin"
        ),
        action=(
            "hauls the coil up hand over hand and climbs from one spar to the next along "
            "the rigging"
        ),
        environment="the wet foredeck and lower rigging of an 1840s sailing ship at sea",
        lighting="hard gray daylight with white water breaking over the bow",
        camera_move="handheld",
        direction=(
            "Ishmael climbs upward and forward along the stays while the camera holds "
            "beside him at deck level"
        ),
        blocking=(
            "the sailor in oilskin stands 2 m aft at the pin rail while Ishmael works "
            "forward of him at the bowsprit"
        ),
        stillness="both men keep their feet firm on the wet deck throughout",
        style=DEFAULT_STYLE,
        audio="rope through a block, water on planks, wind in rigging, no dialogue",
    ),

    # 016_sweeping.png -> 017_paid.png
    "who_is_not_a_slave": ShotSpec(
        shot_type="medium",
        lens="35mm",
        subject=(
            "Ishmael, a man in a plain work shirt, sweeping water off the "
            "forecastle planks, and an old captain in a heavy coat on the deck above him"
        ),
        action=(
            "sweeps in long even strokes across the planks, pauses at the capstan, and "
            "looks up once"
        ),
        environment="the forecastle of an 1840s sailing ship in a working sea",
        lighting="hard gray daylight from a break in the cloud, spray-lit",
        camera_move="static",
        direction=(
            "Ishmael works facing screen right along the planks while the captain above "
            "him holds his ground facing down at the rail"
        ),
        blocking=(
            "the captain stands 4 m above and 3 m aft at the deck rail, one arm up "
            "in a flat command"
        ),
        stillness="the captain's arm stays up without moving, the broom rests against the rail",
        style=DEFAULT_STYLE,
        audio="broom on wet planks, water draining through the scuppers, wind, no dialogue",
    ),

    # 017_paid.png -> 018_pure_air.png
    "being_paid": ShotSpec(
        shot_type="close_up",
        lens="85mm",
        subject=(
            "a ship's purser in a plain coat pressing coins into Ishmael's open palm, "
            "with men queuing at the cabin door further back on deck"
        ),
        action=(
            "counts three coins into Ishmael's open palm and then draws his hand back "
            "while Ishmael closes his fingers over them"
        ),
        environment="the open deck of a working ship with a cabin door and a rail behind",
        lighting="low warm deck-lamp light with cool daylight from the open sea",
        camera_move="dolly_out",
        direction=(
            "the coins move from the purser's hand at frame right into Ishmael's palm at "
            "frame left, then the view widens back toward the cabin door"
        ),
        blocking=(
            "the queue of men stays 3 m aft at the cabin door while the two men at the "
            "rail stay in the foreground"
        ),
        stillness="Ishmael's elbow stays tight to his side while his fingers close",
        style=DEFAULT_STYLE,
        audio="coins on palm, hull working, canvas above, wind, no dialogue",
    ),

    # 018_pure_air.png -> 019_whaler.png
    "pure_air": ShotSpec(
        shot_type="wide",
        lens="24mm",
        subject=(
            "Ishmael, a man in a plain work shirt, and two sailors standing "
            "at the forecastle rail out of the wind"
        ),
        action=(
            "brace at the rail and draw breath as a gust fills the canvas overhead and "
            "spray crosses the rail"
        ),
        environment="the forecastle of a working ship at dawn with the officers' quarterdeck behind",
        lighting="cold dawn light with a low band of gold on the horizon",
        camera_move="dolly_in",
        direction=(
            "the three men face forward into the headwind while the camera pushes in "
            "toward them along the deck"
        ),
        blocking=(
            "the two sailors stand 1 m to either side of Ishmael along the rail, all "
            "three facing the same way"
        ),
        stillness="their feet stay firm at the rail and their coats stream the same way",
        style=DEFAULT_STYLE,
        audio="wind across the rail, canvas snapping, spray on planks, no dialogue",
    ),

    # 019_whaler.png -> 020_forbidden.png
    "fates_programme": ShotSpec(
        shot_type="medium",
        lens="50mm",
        subject=(
            "Ishmael, a man in his early thirties in a work jacket, watching workers on a "
            "whaling ship taking stores aboard alongside a dock"
        ),
        action=(
            "stands still and follows with his eyes as workers roll barrels forward and "
            "coil line on deck"
        ),
        environment="a whaling ship's deck at dusk with barrels, coils and standing rigging",
        lighting="low dusk light through the rigging with hard bar shadows across the deck",
        camera_move="dolly_in",
        direction=(
            "Ishmael stays at frame left facing screen right toward the deck while the "
            "barrels roll left to right across the frame behind him"
        ),
        blocking=(
            "the workers stay 5 m aft along the deck line while Ishmael holds his "
            "position at the fore rail"
        ),
        stillness="Ishmael keeps both feet firm and only his eyes travel across the frame",
        style=DEFAULT_STYLE,
        audio="barrels rolling on planks, line flaking, dock gulls, no dialogue",
    ),

    # 020_forbidden.png -> 021_phantom.png
    "great_whale": ShotSpec(
        shot_type="medium_wide",
        lens="50mm",
        subject=(
            "Ishmael, a small figure in a work jacket at the bow rail of a whaling ship, "
            "and an immense sperm whale far out in the water"
        ),
        action=(
            "grips the rail and watches as the whale rolls its island-length back up "
            "through the dark water and slips down again"
        ),
        environment="open ocean at night under low fog with the ship bow in the foreground",
        lighting="moonless low-key darkness with a faint sheen on the water",
        camera_move="dolly_in",
        direction=(
            "the whale travels screen right to screen left across the far water while "
            "Ishmael stays at the rail facing out"
        ),
        blocking=(
            "the whale stays far offshore at 300 m while Ishmael holds the near rail at "
            "the bottom of frame"
        ),
        stillness="Ishmael's hands stay closed on the rail and he does not step back",
        style=DEFAULT_STYLE,
        audio="low swell, hull groans, one long distant exhalation, no dialogue",
    ),

    # 021_phantom.png -> 022_forbidden_seas.png
    "forbidden_seas": ShotSpec(
        shot_type="extreme_wide",
        lens="24mm",
        subject=(
            "a whaling ship under full sail with Ishmael small at the bow, the last "
            "harbour light a single point astern"
        ),
        action="sails on as the harbour light shrinks and the dark headlands fall away behind",
        environment="a vast unfamiliar ocean at dusk with the coast line low on the horizon",
        lighting="last dusk light fading to blue, no sun on the water",
        camera_move="dolly_out",
        direction=(
            "the ship sails forward away from the coast and the coast slides toward the "
            "left edge of frame and out"
        ),
        stillness="the hull holds a steady line and the sail keeps its cut without flogging",
        style=DEFAULT_STYLE,
        audio="open ocean wind, steady canvas, no bell, no dialogue",
    ),

    # 022_forbidden_seas.png -> 023_wonder_world.png
    "wonder_world": ShotSpec(
        shot_type="extreme_wide",
        lens="35mm",
        subject=(
            "an immense ocean vista opening ahead of the ship with several distant whale "
            "backs surfacing in a loose procession and one pale whale rising pale as a "
            "hill of snow"
        ),
        action=(
            "rolls at the surface in a slow line while the pale whale lifts its bulk clear "
            "of the water and settles back"
        ),
        environment="moonlit fog over open water as far as the eye can see",
        lighting="moonlight through fog, low-key silver on the water, no glow",
        camera_move="dolly_in",
        direction=(
            "the whales move across the far water from screen right toward screen left "
            "while the camera pushes slowly forward toward them"
        ),
        stillness="the ship's rail stays in place at the bottom of frame and no boat leaves it",
        style=DEFAULT_STYLE,
        audio="slow swell, long exhalations, canvas above, no dialogue",
    ),
}

#: adaptation.yaml sahne sırasıyla birebir aynı sıra.
SCENE_IDS: tuple[str, ...] = (
    "call_me_ishmael",
    "november_in_the_soul",
    "substitute_for_pistol",
    "insular_city",
    "silent_sentinels",
    "landsmen_at_the_edge",
    "extremest_limit",
    "magnetic_water",
    "path_to_water",
    "meditation_and_water",
    "magic_stream",
    "the_missing_charm",
    "phantom_of_life",
    "never_a_passenger",
    "before_the_mast",
    "who_is_not_a_slave",
    "being_paid",
    "pure_air",
    "fates_programme",
    "great_whale",
    "forbidden_seas",
    "wonder_world",
)


def shot_for_scene_id(scene_id: str) -> ShotSpec:
    """Sahne kimliğinden ShotSpec döner."""
    try:
        return SCENE_SHOTS[scene_id]
    except KeyError:  # pragma: no cover - yalnızca hata yolu
        raise KeyError(
            f"scene {scene_id!r} tanımlı değil; bilinen sahneler: "
            f"{', '.join(SCENE_IDS)}"
        ) from None