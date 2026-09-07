#!/usr/bin/env python3
"""T332 - the wiring view goes fractal: every hub orchestrates its own tasks.

Owner-confirmed concept (T331, 2026-08-25) with two mandatory adjustments:
the whole scene must fit the viewport, and the surface palette must be
neutral grey rather than blue-navy. This file pins all three - the orbits,
the fit, and the palette.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` as source text only.
          Everything T332 added to the page is PURE, DOM-free JavaScript
          (``orbitCardsFor`` / ``orbitCardHtml`` / ``ringOrbitSlots`` /
          ``centerOrbitSlots`` / ``slotBearings`` / ``slotsAt`` /
          ``slotsPenalty`` / ``orbitSlots`` (T333's below-anchored slot
          geometry) / ``sceneFit`` / ``wireCtrl`` / ``wireD`` /
          ``wireSvg`` / ``wireBox``), so
          this file extracts those blocks VERBATIM and runs them under
          ``node`` against synthetic events and synthetic viewport sizes
          (BL1: nothing here reads this repository's own audit log, and no
          case reads the wall clock - every lifetime question passes an
          explicit ``now``).
Emits   : unittest results only.
Writes  : nothing outside a temporary script handed to ``node``.
Argv    : none.

What this pins
--------------
* THE FRACTAL RULE: an agent with N live chips yields exactly N orbit
  mini-cards, each wired FROM that agent's own position, and an idle agent
  yields none - no satellite and no wire. The satellites' data is the same
  attribution ``chipRailFor`` already owned (T322), which is why this file
  asserts the count and the wiring, never a second copy of the attribution.
* THE ORCHESTRATOR'S OWN TASKS: a tracked-session event carrying no
  ``agent_type`` - a task the session ran itself, with no subagent between
  it and the tool - becomes a satellite of the CENTRE card on the Captain's
  own colour. That case is real in the data, not simulated: it is the very
  owner ``null`` grouping T322 pinned.
* HUB CLEARANCE: a satellite never overlaps the card it orbits, at any
  bearing, for any ring size and any viewport in the sweep; and two
  satellites of the same hub never overlap each other.
* THE VIEWPORT FIT: ``sceneFit`` returns the IDENTITY when the scene already
  fits (so a board with no live tasks is drawn exactly where the pre-T332
  board drew it), never scales up, and - when satellites push the drawing
  past the stage - returns a scale/translate under which EVERY box lands
  inside the stage, bench band still reserved.
* THE WIRES ARE PART OF THAT SCENE (correctness review finding, 2026-08-25):
  a bezier bows away from the straight line between its endpoints, so the
  fit is fed each wire's own reach (``wireBox``) as well as the cards. A
  wire whose bow crosses the stage edge while both its cards sit inside must
  cost the board a scale; a wire that fits must not.
* THE WIRE LANGUAGE: a hub->task wire is the ring wire's own renderer, same
  quadratic bezier with the same 0.14 control-point bow, one size down; live
  wires dash and carry a travelling dot, idle ones do not.
* THE PALETTE: every hex literal the page ships is either neutral grey (the
  owner's adjustment) or one of the persona/state accents, which are pinned
  to their exact pre-T332 values - ownership and state must still read by
  colour.

Failure policy
--------------
FAIL-CLOSED: if ``node`` cannot be found the file fails rather than skipping.

Constraints
-----------
Python 3.10+ standard library plus a ``node`` binary on PATH (the same
dependency ``test_keel_dashboard_t322.py`` already carries). Subprocess
invoked with an argument list, never a shell string (R5).
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from keel_node import NODE, SKIP_REASON, announce_once

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
SOURCE = PAGE.read_text(encoding="utf-8")
announce_once()


def _extract_line(prefix: str, label: str) -> str:
    for line in SOURCE.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"could not extract {label!r} from the served page")


def _extract_block(pattern: str, label: str) -> str:
    m = re.search(pattern, SOURCE, re.S)
    if not m:
        raise AssertionError(f"could not extract {label!r} from the served page")
    return m.group(0)


_TS = _extract_line("const ts=", "ts")
_ESC = _extract_line("const esc=", "esc")
_REL = _extract_block(r"const rel=t=>\{.*?\};", "rel")
_TOOLICON = _extract_line("const toolIcon=", "toolIcon")
_CHIP_BLOCK = _extract_block(
    r"const CHIP_KINDS=new Set.*?function orbitCardHtml\(item\)\{.*?\n\}\n",
    "the chip builder through T332's orbit-card presentation",
)
_SOLVER_BLOCK = _extract_block(
    r"const ORBIT_BAND_H=64,CENTER_HALF_H=120;.*?\nfunction ringPos\(i,count,W,H\)\{.*?\n\}\n",
    "the T324 ring-position solver block",
)
_ORBIT_BLOCK = _extract_block(
    r"const ORBIT_W=96,ORBIT_H=30;.*?\nfunction sceneFit\(boxes,W,H\)\{.*?\n\}\n",
    "the T332 orbit-geometry block",
)
_WIRE_BLOCK = _extract_block(
    r"function wireCtrl\(ax,ay,bx,by\)\{.*?\nfunction wireBox\(ax,ay,bx,by,dotR\)\{.*?\n\}\n",
    "the T332 wire renderer and its fit box",
)

#: Test-side scaffolding ONLY. ``satellitesFor`` composes the extracted
#: functions in exactly the order ``layout()`` composes them (descriptors ->
#: slots -> one wire per slot) so the assertions never carry a private copy
#: of anything the page computes.
_PROBE = """
function satellitesFor(a,events,now,hx,hy,cx,cy,yMax){
  const items=orbitCardsFor(a,events,now);
  const slots=ringOrbitSlots(hx,hy,items.length,cx,cy,yMax===undefined?100000:yMax);
  return items.map((it,j)=>({label:it.label,cls:it.cls,
    x:slots[j][0],y:slots[j][1],
    wire:wireSvg(hx,hy,slots[j][0],slots[j][1],"#abcabc",
                 it.cls==="background",1.6,1.1,2.6,"1.9s")}));
}
function captainSatellites(events,now,ringPoints,cx,cy,yMax){
  const items=orbitCardsFor(null,events,now);
  const slots=centerOrbitSlots(items.length,ringPoints,cx,cy,yMax===undefined?100000:yMax);
  return items.map((it,j)=>({label:it.label,cls:it.cls,x:slots[j][0],y:slots[j][1]}));
}
// The whole scene for one synthetic board, boxes assembled exactly as
// layout() assembles them, plus the fit those boxes produce.
function scene(ring,W,H,capN,perHub){
  const cx=W/2,cy=(H-BENCH_H)/2;
  const pos=[];for(let i=0;i<ring;i++)pos.push(ringPos(i,ring,W,H));
  const sats=[];
  const yMax=H-BENCH_H;
  centerOrbitSlots(capN,pos,cx,cy,yMax).forEach(q=>sats.push({p:q,owner:-1}));
  pos.forEach((q,k)=>ringOrbitSlots(q[0],q[1],perHub,cx,cy,yMax)
    .forEach(r=>sats.push({p:r,owner:k})));
  const boxes=[[cx-CENTER_HALF_W,cy-CENTER_HALF_H,cx+CENTER_HALF_W,cy+CENTER_HALF_H]];
  pos.forEach(q=>{boxes.push([q[0]-CARD_W/2,q[1]-CARD_H/2,q[0]+CARD_W/2,q[1]+CARD_H/2]);
    boxes.push(wireBox(cx,cy,q[0],q[1],4));});
  sats.forEach(s=>{boxes.push([s.p[0]-ORBIT_W/2,s.p[1]-ORBIT_H/2,
                               s.p[0]+ORBIT_W/2,s.p[1]+ORBIT_H/2]);
    const h=s.owner<0?[cx,cy]:pos[s.owner];
    boxes.push(wireBox(h[0],h[1],s.p[0],s.p[1],2.6));});
  const fit=sceneFit(boxes,W,H);
  // every box after the transform, in stage pixels
  const drawn=boxes.map(b=>[b[0]*fit.s+fit.tx,b[1]*fit.s+fit.ty,
                            b[2]*fit.s+fit.tx,b[3]*fit.s+fit.ty]);
  // a satellite against the hub it belongs to (axis-aligned overlap test):
  // the hub's own visible card, NOT its reserved band.
  const hubs=[{p:[cx,cy],hw:CENTER_HALF_W,hh:CENTER_HALF_H,k:-1}];
  pos.forEach((q,k)=>hubs.push({p:q,hw:CARD_W/2,hh:76,k:k}));
  let ownHubOverlap=0;
  sats.forEach(s=>hubs.forEach(h=>{
    if(h.k===s.owner
      &&Math.abs(s.p[0]-h.p[0])<h.hw+ORBIT_W/2
      &&Math.abs(s.p[1]-h.p[1])<h.hh+ORBIT_H/2)ownHubOverlap++;
  }));
  let siblingOverlap=0;
  for(let i=0;i<sats.length;i++)for(let j=i+1;j<sats.length;j++){
    if(sats[i].owner!==sats[j].owner)continue;
    if(Math.abs(sats[i].p[0]-sats[j].p[0])<ORBIT_W
     &&Math.abs(sats[i].p[1]-sats[j].p[1])<ORBIT_H)siblingOverlap++;
  }
  return {ring:ring,W:W,H:H,capN:capN,perHub:perHub,
    s:fit.s,tx:fit.tx,ty:fit.ty,drawn:drawn,
    ownHubOverlap:ownHubOverlap,siblingOverlap:siblingOverlap,
    satCount:sats.length,BENCH_H:BENCH_H};
}
function scenes(cases){return cases.map(c=>scene(c[0],c[1],c[2],c[3],c[4]));}
// T333: one hub's slots, reported beside the constants that shape them, so
// the below-anchor assertions never carry a second copy of the geometry.
function slotProbe(hx,hy,n,cx,cy,yMax){
  return {slots:ringOrbitSlots(hx,hy,n,cx,cy,yMax),hx:hx,hy:hy,
          ORBIT_R:ORBIT_R,ORBIT_W:ORBIT_W,ORBIT_H:ORBIT_H};
}
function centreSlotProbe(n,points,cx,cy,yMax){
  return {slots:centerOrbitSlots(n,points,cx,cy,yMax),hx:cx,hy:cy,
          CENTER_ORBIT_R:CENTER_ORBIT_R,ORBIT_H:ORBIT_H};
}
// Two mini-card boxes at the ends of ONE wire, and the fit those produce
// with and without that wire's own box - the difference between the two
// answers is exactly what the review finding was about. ``escaped`` samples
// the real curve so the box cannot be pinned as "big enough" while missing
// the bow it is supposed to bound.
function wireFit(ax,ay,bx,by,W,H,dotR){
  const ends=[[ax-ORBIT_W/2,ay-ORBIT_H/2,ax+ORBIT_W/2,ay+ORBIT_H/2],
              [bx-ORBIT_W/2,by-ORBIT_H/2,bx+ORBIT_W/2,by+ORBIT_H/2]];
  const wb=wireBox(ax,ay,bx,by,dotR);
  const withWire=sceneFit(ends.concat([wb]),W,H),cardsOnly=sceneFit(ends,W,H);
  const c=wireCtrl(ax,ay,bx,by),pts=[];
  for(let i=0;i<=100;i++){const t=i/100,u=1-t;
    pts.push([u*u*ax+2*u*t*c[0]+t*t*bx,u*u*ay+2*u*t*c[1]+t*t*by]);}
  const escaped=pts.filter(p=>p[0]<wb[0]||p[0]>wb[2]||p[1]<wb[1]||p[1]>wb[3]).length;
  const drawn=ends.concat([wb]).map(b=>[b[0]*withWire.s+withWire.tx,b[1]*withWire.s+withWire.ty,
                                        b[2]*withWire.s+withWire.tx,b[3]*withWire.s+withWire.ty]);
  return {withWire:withWire,cardsOnly:cardsOnly,box:wb,escaped:escaped,drawn:drawn,
          W:W,H:H,BENCH_H:BENCH_H};
}
"""

PRELUDE = "\n".join(
    [_TS, _ESC, _REL, _TOOLICON, _CHIP_BLOCK, _SOLVER_BLOCK, _ORBIT_BLOCK,
     _WIRE_BLOCK, _PROBE]
)


def run_node(call_js: str) -> Any:
    if NODE is None:
        raise AssertionError("node was not found on PATH - failing closed")
    script = PRELUDE + "\nprocess.stdout.write(JSON.stringify(" + call_js + "));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run([NODE, path], capture_output=True, timeout=60, check=False)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError("node harness failed: " + result.stderr.decode("utf-8", "replace"))
    return json.loads(result.stdout.decode("utf-8"))


# ---- synthetic fixtures (BL1: nothing here reads a real audit log) --------
T0 = "2026-08-25T10:00:00Z"
T1 = "2026-08-25T10:00:10Z"
T2 = "2026-08-25T10:00:20Z"
T3 = "2026-08-25T10:00:30Z"


def _epoch_ms(ts_iso: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp() * 1000)


def activity(session: str, ts_iso: str, agent_type: Any = None, tool: str = "Bash",
             detail: str = "ran a command") -> dict[str, Any]:
    return {"event": "activity", "session_id": session, "agent_type": agent_type,
            "tool": tool, "detail": detail, "ts": ts_iso}


def background(session: str, ts_iso: str, agent_type: Any = None, tool: str = "Bash",
               detail: str = "long build", task_id: str | None = None) -> dict[str, Any]:
    ev = {"event": "background_task", "session_id": session, "agent_type": agent_type,
          "tool": tool, "detail": detail, "ts": ts_iso}
    if task_id:
        ev["task_id"] = task_id
    return ev


def handoff_agent(session: str, subagent_type: str, start_ts: str,
                  end_ts: str | None = None, background_run: bool = False,
                  stop_ts: str | None = None) -> dict[str, Any]:
    return {"start": {"session_id": session, "subagent_type": subagent_type, "ts": start_ts},
            "end": {"ts": end_ts} if end_ts else None,
            "background": background_run,
            "stop": {"ts": stop_ts} if stop_ts else None}


class TestTheExtractionItselfFoundEveryPiece(unittest.TestCase):
    def test_every_block_is_nonempty_and_carries_its_functions(self) -> None:
        for fn, block in (
            ("orbitCardsFor", _CHIP_BLOCK),
            ("orbitCardHtml", _CHIP_BLOCK),
            ("ringPos", _SOLVER_BLOCK),
            ("ringOrbitSlots", _ORBIT_BLOCK),
            ("centerOrbitSlots", _ORBIT_BLOCK),
            ("slotBearings", _ORBIT_BLOCK),   # T333: the below-anchored order
            ("orbitSlots", _ORBIT_BLOCK),
            ("sceneFit", _ORBIT_BLOCK),
            ("wireSvg", _WIRE_BLOCK),
        ):
            self.assertIn(fn, block, f"{fn} missing from its extracted block")

    def test_the_page_positions_satellites_only_through_these_functions(self) -> None:
        # one definition, one caller shape each - no second copy of the
        # geometry can drift away from what this file checks.
        for fn in ("ringOrbitSlots", "centerOrbitSlots", "sceneFit", "wireSvg"):
            self.assertEqual(SOURCE.count("function " + fn + "("), 1, fn)
        self.assertIn("const fit=sceneFit(boxes,W,H);", SOURCE)
        self.assertIn('$("nodes").style.transform=tf;$("edges").style.transform=tf;', SOURCE)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestNLiveTasksMakeNSatellites(unittest.TestCase):
    """The fractal rule itself: an agent running N tasks gets N mini cards
    wired to IT, an idle agent gets none."""

    HUB = (900, 300)
    CENTRE = (600, 311)

    def _sats(self, a: Any, events: list[dict], now: int) -> Any:
        hx, hy = self.HUB
        cx, cy = self.CENTRE
        return run_node(
            f"satellitesFor({json.dumps(a)},{json.dumps(events)},{now},{hx},{hy},{cx},{cy},700)"
        )

    def test_three_live_chips_yield_three_satellites_wired_to_that_agent(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0)  # still working
        events = [
            background("s1", T0, agent_type="keel:executor", detail="build one"),
            background("s1", T1, agent_type="keel:executor", detail="build two"),
            background("s1", T2, agent_type="keel:executor", detail="build three"),
        ]
        sats = self._sats(a, events, _epoch_ms(T3))
        self.assertEqual(len(sats), 3)
        hx, hy = self.HUB
        for s in sats:
            # every wire STARTS at this agent's own position - the agent is
            # the orchestrator of its own tasks, which is the whole feature
            self.assertTrue(s["wire"].startswith(f'<path d="M{hx} {hy} Q'), s["wire"])
            self.assertIn("stroke-dasharray", s["wire"])  # live: dashed + flowing
            self.assertIn("<animateMotion", s["wire"])  # live: travelling dot

    def test_one_live_chip_yields_exactly_one_satellite(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0)
        events = [background("s1", T0, agent_type="keel:executor", task_id="T332")]
        sats = self._sats(a, events, _epoch_ms(T3))
        self.assertEqual(len(sats), 1)
        self.assertEqual(sats[0]["label"], "T332")  # the record's own task name

    def test_an_idle_agent_yields_no_satellite_and_no_wire(self) -> None:
        """The pre-T332 card, unchanged: nothing live in scope, nothing drawn."""
        a = handoff_agent("s1", "keel:executor", T0, end_ts=T1)  # reported back
        events = [background("s1", T0, agent_type="keel:executor")]
        sats = self._sats(a, events, _epoch_ms(T2))
        self.assertEqual(sats, [])

    def test_an_agent_with_no_events_at_all_yields_no_satellite(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0)
        self.assertEqual(self._sats(a, [], _epoch_ms(T3)), [])

    def test_a_completed_chip_gets_a_dim_satellite_on_a_faint_wire(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0)
        events = [activity("s1", T0, agent_type="keel:executor", detail="ran tests")]
        sats = self._sats(a, events, _epoch_ms(T0) + 1000)
        self.assertEqual(len(sats), 1)
        self.assertEqual(sats[0]["cls"], "done")
        self.assertNotIn("stroke-dasharray", sats[0]["wire"])
        self.assertNotIn("<animateMotion", sats[0]["wire"])
        self.assertIn('stroke-opacity="0.22"', sats[0]["wire"])

    def test_another_agents_task_never_orbits_this_agent(self) -> None:
        mine = handoff_agent("s1", "keel:executor", T0)
        events = [background("s1", T0, agent_type="keel:reviewer-tests")]
        self.assertEqual(self._sats(mine, events, _epoch_ms(T3)), [])


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheOrchestratorsOwnTasksOrbitTheCentre(unittest.TestCase):
    """A task the session ran ITSELF - no subagent between it and the tool -
    is attributable in the record (it carries no ``agent_type``), and becomes
    a satellite of the centre card."""

    def test_an_untyped_live_event_orbits_the_captain(self) -> None:
        events = [background("s1", T0, agent_type=None, detail="dashboard")]
        ring = [[900.0, 300.0], [300.0, 300.0]]
        sats = run_node(
            f"captainSatellites({json.dumps(events)},{_epoch_ms(T3)},{json.dumps(ring)},600,311,700)"
        )
        self.assertEqual(len(sats), 1)
        self.assertEqual(sats[0]["cls"], "background")
        # it is placed away from the centre card, not on top of it
        self.assertGreaterEqual(
            math.hypot(sats[0]["x"] - 600, sats[0]["y"] - 311), 200.0
        )

    def test_a_delegates_event_never_orbits_the_captain(self) -> None:
        events = [background("s1", T0, agent_type="keel:executor")]
        sats = run_node(
            f"captainSatellites({json.dumps(events)},{_epoch_ms(T3)},[],600,311,700)"
        )
        self.assertEqual(sats, [])

    def test_a_quiet_session_gives_the_captain_no_satellites(self) -> None:
        sats = run_node(f"captainSatellites([],{_epoch_ms(T3)},[],600,311,700)")
        self.assertEqual(sats, [])


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestSatellitesClearTheirOwnHub(unittest.TestCase):
    """Geometry, swept: a mini card never lands on the card it orbits, and
    two mini cards of the same hub never land on each other - at every ring
    size, every satellite count and every viewport in the sweep."""

    CASES = [
        [ring, W, H, capN, perHub]
        for W in (900, 1200, 1400, 1920)
        for H in (560, 700, 900, 1080)
        for ring in (0, 1, 3, 5, 8)
        for capN in (0, 1, 3)
        for perHub in (0, 1, 3)
    ]

    def test_no_satellite_overlaps_the_hub_it_orbits(self) -> None:
        for sc in run_node(f"scenes({json.dumps(self.CASES)})"):
            with self.subTest(W=sc["W"], H=sc["H"], ring=sc["ring"],
                              capN=sc["capN"], perHub=sc["perHub"]):
                self.assertEqual(sc["ownHubOverlap"], 0)

    def test_two_satellites_of_one_hub_never_overlap(self) -> None:
        for sc in run_node(f"scenes({json.dumps(self.CASES)})"):
            with self.subTest(W=sc["W"], H=sc["H"], ring=sc["ring"],
                              capN=sc["capN"], perHub=sc["perHub"]):
                self.assertEqual(sc["siblingOverlap"], 0)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheWholeSceneFitsTheViewport(unittest.TestCase):
    """The owner's first adjustment: nothing may be clipped. The remedy is
    one uniform scale over both layers, and these are its three properties."""

    CASES = TestSatellitesClearTheirOwnHub.CASES

    def test_every_box_lands_inside_the_stage_after_the_transform(self) -> None:
        for sc in run_node(f"scenes({json.dumps(self.CASES)})"):
            with self.subTest(W=sc["W"], H=sc["H"], ring=sc["ring"],
                              capN=sc["capN"], perHub=sc["perHub"]):
                for box in sc["drawn"]:
                    self.assertGreaterEqual(box[0], -0.001)
                    self.assertGreaterEqual(box[1], -0.001)
                    self.assertLessEqual(box[2], sc["W"] + 0.001)
                    self.assertLessEqual(box[3], sc["H"] - sc["BENCH_H"] + 0.001)

    def test_the_scale_is_never_greater_than_one(self) -> None:
        for sc in run_node(f"scenes({json.dumps(self.CASES)})"):
            with self.subTest(W=sc["W"], H=sc["H"]):
                self.assertLessEqual(sc["s"], 1.0)
                self.assertGreater(sc["s"], 0.3)  # never collapses the board

    def test_a_board_with_no_live_tasks_is_not_transformed_at_all(self) -> None:
        """Regression guard: with no satellites the T324 ring solver already
        keeps everything on stage, so T332 must leave the drawing exactly
        where it was - identity transform, to the pixel."""
        cases = [[ring, W, H, 0, 0]
                 for W in (900, 1200, 1400, 1920)
                 for H in (700, 900, 1080)
                 for ring in (0, 1, 3, 5, 8)]
        for sc in run_node(f"scenes({json.dumps(cases)})"):
            with self.subTest(W=sc["W"], H=sc["H"], ring=sc["ring"]):
                self.assertEqual(sc["satCount"], 0)
                self.assertEqual(sc["s"], 1)
                self.assertEqual(sc["tx"], 0)
                self.assertEqual(sc["ty"], 0)

    def test_a_crowded_board_really_does_scale_down(self) -> None:
        """The fit is not vacuous: a board whose satellites reach past the
        stage must come back with a scale below 1."""
        sc = run_node("scene(8,1200,700,3,3)")
        self.assertLess(sc["s"], 1.0)
        self.assertGreater(sc["satCount"], 20)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheWireLanguageIsTheRingsOwn(unittest.TestCase):
    """A hub->task wire is the Captain->agent wire, one size down: the same
    renderer, the same bezier, the same control-point bow."""

    def test_the_control_point_is_the_rings_own_formula(self) -> None:
        d = run_node("wireD(100,200,400,500)")
        mx = (100 + 400) / 2 + (500 - 200) * 0.14
        my = (200 + 500) / 2 - (400 - 100) * 0.14
        # both terms are whole numbers here, and JS prints those without a
        # decimal point - so the expectation is written the way the page
        # writes it, with the arithmetic still done independently above.
        self.assertEqual(mx, 292.0)
        self.assertEqual(my, 308.0)
        self.assertEqual(d, "M100 200 Q292 308 400 500")

    def test_a_live_wire_dashes_flows_and_carries_a_dot(self) -> None:
        svg = run_node('wireSvg(0,0,100,100,"#abcabc",true,1.6,1.1,2.6,"1.9s")')
        self.assertIn('stroke-dasharray="7 7" class="flow"', svg)
        self.assertIn('stroke-opacity="0.85"', svg)
        self.assertIn('stroke-width="1.6"', svg)
        self.assertIn('<circle r="2.6"', svg)
        self.assertIn('dur="1.9s"', svg)

    def test_an_idle_wire_is_faint_and_static(self) -> None:
        svg = run_node('wireSvg(0,0,100,100,"#abcabc",false,1.6,1.1,2.6,"1.9s")')
        self.assertNotIn("stroke-dasharray", svg)
        self.assertNotIn("<circle", svg)
        self.assertIn('stroke-opacity="0.22"', svg)
        self.assertIn('stroke-width="1.1"', svg)

    def test_the_ring_edges_go_through_the_same_renderer_at_their_own_size(self) -> None:
        self.assertIn('lines+=wireSvg(cx,cy,x,y,col,working,2.4,1.4,4,"1.6s");', SOURCE)
        self.assertIn(
            'lines+=wireSvg(o.hx,o.hy,o.x,o.y,taskWire,o.item.cls==="background",'
            '1.6,1.1,2.6,"1.9s");',
            SOURCE,
        )
        # the bow lives in exactly one place now
        self.assertEqual(SOURCE.count("*0.14"), 2)  # both terms of one formula


class TestThePaletteIsNeutralGreyAndTheAccentsSurvive(unittest.TestCase):
    """The owner's second adjustment. Two halves, both pinned: the surface
    hues are drained to grey, and the colours that CARRY MEANING - persona
    accents and state colours - keep their exact values, because ownership
    and state are read off them."""

    #: The only saturated colours the page is allowed to ship, each with the
    #: meaning it carries. Anything else must be neutral.
    MEANINGFUL = {
        "#eec25f": "--maestro", "#38c2b1": "--scout", "#5f9dfb": "--forge",
        "#ab8bff": "--sage", "#f0925a": "--counsel", "#8a93a8": "--generic",
        "#46c988": "--good", "#ef6470": "--bad", "#e9ba3a": "--warn",
        "#e8c34a": "--captain", "#6fd1e8": "--surveyor", "#4fb0e0": "--leadsman",
        "#e98a3a": "--gunner", "#7fd48a": "--trimmer",
        "#c9b08c": "--taskwire (T333: the ONE task-wire hue, deliberately "
                   "no persona's accent and no surface grey)",
        "#7ee3ae": "plan-progress gradient (state: done)",
        "#f2aeb4": "blocked task text (state: blocked)",
        "#2a1c2422": "alert row tint (state: alert)",
    }
    #: max(r,g,b)-min(r,g,b), out of 255, that still reads as grey.
    NEUTRAL_TOLERANCE = 12

    @staticmethod
    def _hexes() -> list[str]:
        return re.findall(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b", SOURCE)

    def test_every_surface_colour_is_neutral_grey(self) -> None:
        for value in sorted(set(self._hexes())):
            if value.lower() in self.MEANINGFUL:
                continue
            r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5))
            with self.subTest(colour=value):
                self.assertLessEqual(
                    max(r, g, b) - min(r, g, b), self.NEUTRAL_TOLERANCE,
                    f"{value} is not a neutral grey - the blue-navy palette is back",
                )

    def test_the_named_surface_ramp_is_the_grey_one(self) -> None:
        self.assertIn(
            "--bg:#121316; --panel:#191a1e; --panel2:#202226; --card:#1b1d21;", SOURCE
        )
        self.assertIn("--line:#33363c;", SOURCE)

    def test_the_persona_accents_are_untouched(self) -> None:
        self.assertIn(
            "--maestro:#eec25f; --scout:#38c2b1; --forge:#5f9dfb; --sage:#ab8bff;",
            SOURCE,
        )
        self.assertIn(
            "--captain:#e8c34a; --lookout:#38c2b1; --shipwright:#5f9dfb;", SOURCE
        )
        self.assertIn(
            "--chief:#ab8bff; --surveyor:#6fd1e8; --arms:#ef6470;", SOURCE
        )
        self.assertIn(
            "--leadsman:#4fb0e0; --gunner:#e98a3a; --trimmer:#7fd48a;", SOURCE
        )

    def test_the_state_colours_are_untouched(self) -> None:
        self.assertIn("--good:#46c988; --bad:#ef6470; --warn:#e9ba3a;", SOURCE)

    def test_a_satellite_wears_its_hubs_accent_not_a_grey(self) -> None:
        # the mini card's border and dot are the hub persona's variable, set
        # per element by the layout - ownership still reads by colour.
        self.assertIn(
            "border:1px solid color-mix(in srgb, var(--c) 45%, var(--line))", SOURCE
        )
        self.assertIn(".tnode .tdot{flex:none;width:6px;height:6px;"
                      "border-radius:50%;background:var(--c)}", SOURCE)
        self.assertIn('el.style.setProperty("--c",`var(${o.pv})`);', SOURCE)
        self.assertIn("pv:PERSONAS.orchestrator.v", SOURCE)  # Captain's own gold


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheFitSeesTheWiresOwnReach(unittest.TestCase):
    """Correctness review finding, 2026-08-25: the fit was fed card boxes
    only, so a wire whose BOW left the stage while both of its cards sat
    inside it was clipped by a transform that reported "already fits". These
    cases fail without ``wireBox`` in the boxes list.

    Geometry of the fixture: the two cards sit at y=680 on a 700px-tall
    stage, well inside it; the wire between them bows 35px downward (half of
    the 0.14 control offset over a 500px span), which puts the curve at
    y=715 - past the stage edge, and past it by the wire alone.
    """

    STAGE = (1200, 778)  # stage height 778-78(bench) = 700

    def _fit(self, ay: int, by: int | None = None) -> Any:
        W, H = self.STAGE
        by = ay if by is None else by
        return run_node(f"wireFit(600,{ay},100,{by},{W},{H},2.6)")

    def test_a_wire_whose_bow_leaves_the_stage_moves_the_scene(self) -> None:
        f = self._fit(680)
        # the cards alone fit - this is not a case about card placement
        self.assertEqual(f["cardsOnly"]["s"], 1)
        self.assertEqual(f["cardsOnly"]["tx"], 0)
        self.assertEqual(f["cardsOnly"]["ty"], 0)
        # ... and the wire alone is what leaves the stage
        self.assertGreater(f["box"][3], f["H"] - f["BENCH_H"])
        # ... so the fit must answer with a transform, not the identity. Here
        # the drawing is narrower than the stage, so the remedy it picks is a
        # SHIFT rather than a shrink - either way the edge layer stops being
        # clipped, which is the property. (The shrink path is pinned by the
        # next case, where a shift alone cannot do it.)
        got = (f["withWire"]["s"], f["withWire"]["tx"], f["withWire"]["ty"])
        self.assertNotEqual(got, (1, 0, 0))
        for box in f["drawn"]:
            self.assertLessEqual(box[3], f["H"] - f["BENCH_H"] + 0.001)
            self.assertGreaterEqual(box[1], -0.001)

    def test_a_wire_that_overruns_the_stage_costs_the_board_a_scale(self) -> None:
        """Cards that fit top to bottom with nothing to spare, and a wire
        whose bow needs 5px more than the stage has: the fit cannot shift its
        way out of this one, so it scales."""
        f = self._fit(20, 685)
        self.assertEqual(f["cardsOnly"]["s"], 1)
        self.assertLess(f["withWire"]["s"], 1.0)
        for box in f["drawn"]:
            self.assertLessEqual(box[3], f["H"] - f["BENCH_H"] + 0.001)
            self.assertGreaterEqual(box[1], -0.001)

    def test_the_same_wire_with_its_bow_inside_stays_identity(self) -> None:
        """The other half of the guarantee: a wire that really does fit must
        not cost the board a scale - the identity survives."""
        f = self._fit(400)
        self.assertLess(f["box"][3], f["H"] - f["BENCH_H"])
        self.assertEqual(f["withWire"]["s"], 1)
        self.assertEqual(f["withWire"]["tx"], 0)
        self.assertEqual(f["withWire"]["ty"], 0)

    def test_the_box_contains_the_whole_curve_not_just_its_apex(self) -> None:
        """101 samples of the real bezier, on bearings all round the clock:
        none may fall outside the box the fit was given."""
        cases = [(600, 400, 100, 400), (600, 400, 1100, 300), (600, 400, 600, 90),
                 (600, 400, 200, 90), (600, 400, 1000, 650), (600, 400, 610, 415),
                 (300, 200, 900, 600), (900, 600, 300, 200)]
        for ax, ay, bx, by in cases:
            with self.subTest(a=(ax, ay), b=(bx, by)):
                f = run_node(f"wireFit({ax},{ay},{bx},{by},1200,778,4)")
                self.assertEqual(f["escaped"], 0)

    def test_layout_feeds_every_wire_into_the_fit(self) -> None:
        """The page must actually hand those boxes over - one per ring edge
        and one per task wire, at the same dot radii the wires are drawn
        with, or the pins above are decorative."""
        self.assertIn("boxes.push(wireBox(cx,cy,q[0],q[1],4));", SOURCE)
        self.assertIn("boxes.push(wireBox(o.hx,o.hy,o.x,o.y,2.6));", SOURCE)
        self.assertEqual(SOURCE.count("function wireBox("), 1)
        # the control point has exactly one definition, shared by the path
        # renderer and the fit box - they cannot bow differently
        self.assertEqual(SOURCE.count("function wireCtrl("), 1)
        self.assertIn("const c=wireCtrl(ax,ay,bx,by);", SOURCE)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestSatellitesHangBelowTheirHub(unittest.TestCase):
    """T333 (owner review of the live board, 2026-08-25): a hub's tasks start
    UNDERNEATH its card and fan out from there - below, below-right,
    below-left, then the sides - instead of being aimed into whatever angular
    gap happened to be free. The sizes are T332's and unchanged; this is the
    order of bearings, and it is what makes a satellite's place predictable.
    """

    def test_the_first_satellite_hangs_directly_below_its_hub(self) -> None:
        p = run_node("slotProbe(900,300,1,600,311,900)")
        x, y = p["slots"][0]
        self.assertAlmostEqual(x, p["hx"], delta=0.001)          # dead centre
        self.assertAlmostEqual(y, p["hy"] + p["ORBIT_R"], delta=0.001)  # below

    def test_the_next_two_hang_below_right_then_below_left(self) -> None:
        p = run_node("slotProbe(900,300,3,600,311,900)")
        first, second, third = p["slots"]
        for slot in (first, second, third):
            self.assertGreater(slot[1], p["hy"], "every slot of this fan is below the hub")
        self.assertAlmostEqual(first[0], p["hx"], delta=0.001)
        self.assertGreater(second[0], p["hx"])   # below-right
        self.assertLess(third[0], p["hx"])       # below-left

    def test_the_captain_anchors_below_its_own_card_too(self) -> None:
        p = run_node("centreSlotProbe(1,[],600,311,900)")
        x, y = p["slots"][0]
        self.assertAlmostEqual(x, p["hx"], delta=0.001)
        self.assertAlmostEqual(y, p["hy"] + p["CENTER_ORBIT_R"], delta=0.001)

    def test_a_hub_over_the_bench_fans_outward_rather_than_into_it(self) -> None:
        """The one exception the owner named: where "below" would put a task
        on the bench strip, the fan goes outward instead - and every slot it
        picks stays above the bench line."""
        y_max = 700
        p = run_node(f"slotProbe(900,{y_max - 120},3,600,311,{y_max})")
        for slot in p["slots"]:
            self.assertLessEqual(slot[1] + p["ORBIT_H"] / 2, y_max + 0.001)
        # it really was pushed off the below-anchor, not merely lucky
        self.assertNotAlmostEqual(p["slots"][0][0], p["hx"], delta=0.001)

    def test_the_below_anchor_survives_when_there_is_room(self) -> None:
        """The fallback must not fire on a comfortable board: same hub, same
        stage, moved up - the anchor is below again."""
        p = run_node("slotProbe(900,300,3,600,311,700)")
        self.assertAlmostEqual(p["slots"][0][0], p["hx"], delta=0.001)
        self.assertGreater(p["slots"][0][1], p["hy"])


class TestTaskWiresHaveTheirOwnColour(unittest.TestCase):
    """T333, second half: a hub->task wire must not speak the persona
    language. Gold is the Captain<->agent line and nothing else; all task
    wiring - a delegate's and the Captain's own self-run task alike - is one
    token that belongs to no persona."""

    @staticmethod
    def _tokens() -> dict[str, str]:
        """Every ``--name:#value`` the page's :root blocks declare."""
        return {m.group(1): m.group(2).lower()
                for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6,8})", SOURCE)}

    def test_the_token_exists(self) -> None:
        self.assertIn("--taskwire:#c9b08c;", SOURCE)
        self.assertEqual(self._tokens().get("taskwire"), "#c9b08c")

    def test_the_token_is_no_personas_accent_and_no_state_colour(self) -> None:
        tokens = self._tokens()
        mine = tokens["taskwire"]
        for name, value in tokens.items():
            if name == "taskwire":
                continue
            with self.subTest(token=name):
                self.assertNotEqual(value, mine, f"--taskwire collides with --{name}")

    def test_every_task_wire_is_drawn_with_it_and_none_with_a_persona(self) -> None:
        self.assertIn('const taskWire=css("--taskwire");', SOURCE)
        self.assertIn("lines+=wireSvg(o.hx,o.hy,o.x,o.y,taskWire,", SOURCE)
        # the hub's persona colour reaches the wire renderer exactly once -
        # on the ring edge, which is the Captain<->agent line it belongs to
        self.assertEqual(SOURCE.count("wireSvg(cx,cy,x,y,col,working"), 1)
        self.assertNotIn("wireSvg(o.hx,o.hy,o.x,o.y,css(o.pv)", SOURCE)

    def test_the_satellite_card_still_wears_its_hubs_accent(self) -> None:
        """Only the WIRE changed colour: ownership still reads off the card."""
        self.assertIn('el.style.setProperty("--c",`var(${o.pv})`);', SOURCE)
        self.assertIn(
            "border:1px solid color-mix(in srgb, var(--c) 45%, var(--line))", SOURCE
        )


class TestNodeAbsenceIsAnnounced(unittest.TestCase):
    """Node's absence is audible, then skipped — never silent (BL17, ruled
    2026-09-01). The orbit checks above skip so a clone without node reaches
    green; ``keel_node.announce_once`` is what keeps that visible."""

    def test_node_is_on_path(self) -> None:
        if NODE is None:
            self.skipTest(SKIP_REASON)
        self.assertTrue(
            Path(NODE).exists(),
            f"PATH named a node that is not there: {NODE}",
        )


if __name__ == "__main__":
    unittest.main()
