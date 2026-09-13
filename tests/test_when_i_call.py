import io
import json
import unittest
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import app
from poker.board_texture import FLOP_FILTER_KEYS, classify_flop
from poker.metrics.base import get_metric, load_builtin_metrics
from poker.metrics.when_i_call import WhenICallMetric, extract_hero_call_spots, hand_matches_call_options
from poker.metrics.when_i_raise import WhenIRaiseMetric, classify_flop_to_turn
from poker.models import Action, Hand, HandDataset
from poker.parser import parse_hand
from poker.replay.matchers import matcher_for
from poker.replay.service import get_replay
from poker.service import AnalysisService


def action(player, kind, street="flop", amount=50, pot=100):
    return Action(street, player, kind, amount=amount, pot_before=pot, is_hero=player == "Hero")


def call_line(street="flop", kind="bet", size=50):
    return [action("Villain", kind, street, size), action("Hero", "call", street, size, 100 + size)]


def make_hand(actions=None, *, hand_id="call", hero="BTN", opponent="BB", others=(), cards=None, max_players=6):
    positions = ("BTN", "SB", "BB", "UTG", "HJ", "CO") if max_players == 6 else (
        "BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO",
    )
    names = {i: "Hero" if pos == hero else "Villain" if pos == opponent else pos
             for i, pos in enumerate(positions, 1)}
    folds = [action(name, "fold", "preflop", 0) for name in names.values()
             if name not in {"Hero", "Villain", *others}]
    return Hand(
        hand_id=hand_id, datetime=datetime(2026, 9, 12), table_name="Call Test", stakes="0.5/1",
        max_players=max_players, hero_seat=next(i for i, name in names.items() if name == "Hero"),
        hero_cards="Qc Jd", hero_invested=0, hero_collected=0, hero_returned=0, total_pot=0,
        rake=0, jackpot=0, bingo=0, fortune=0, tax=0, source_file="call.txt", button_seat=1,
        seat_names=names, actions=folds + (call_line() if actions is None else actions),
        shown_cards=cards or {}, flop_cards=("As", "7h", "2h"), went_to_flop=True,
    )


class WhenICallTests(unittest.TestCase):
    def setUp(self):
        self.metric = WhenICallMetric()

    def test_detection_and_facing_action_rates(self):
        lines = [
            call_line(),
            call_line(kind="raise"),
            [action("Hero", "check")] + call_line(),
            [action("Hero", "bet")] + call_line(kind="raise"),
        ]
        hands = [make_hand(line, hand_id=str(i)) for i, line in enumerate(lines)]
        for hand in hands:
            spots = extract_hero_call_spots(hand)
            self.assertEqual(len(spots), 1)
            self.assertEqual(spots[0].aggressor, "Villain")
        result = self.metric.compute(HandDataset(hands))
        self.assertEqual((result["spot_count"], result["hand_count"]), (4, 4))
        self.assertEqual(result["facing_bet"], {"count": 2, "pct": 50.0})
        self.assertEqual(result["facing_raise"], {"count": 2, "pct": 50.0})
        self.assertNotIn("call", result)

    def test_limp_blind_completion_and_inactive_aggression_are_excluded(self):
        cases = {
            "limp": [action("Villain", "posts big blind", "preflop", 1), action("Hero", "call", "preflop", 1)],
            "sb-completion": [action("Hero", "posts small blind", "preflop", .5),
                              action("Villain", "posts big blind", "preflop", 1), action("Hero", "call", "preflop", .5)],
            "unopposed-call": [action("Villain", "check"), action("Hero", "call")],
            "hero-aggression": [action("Villain", "bet"), action("Hero", "raise"),
                                action("Villain", "call"), action("Hero", "call")],
            "street-reset": [action("Villain", "bet"), action("Hero", "call", "turn")],
            "zero-pot": [action("Villain", "bet", pot=0), action("Hero", "call")],
            "negative-pot": [action("Villain", "raise", pot=-1), action("Hero", "call")],
            "folded-hero": [action("Hero", "fold")] + call_line(),
            "folded-aggressor": [action("Villain", "bet"), action("Villain", "fold"), action("Hero", "call")],
        }
        for label, line in cases.items():
            with self.subTest(label=label):
                hand = make_hand(line, hero="SB" if label == "sb-completion" else "BTN")
                result = self.metric.compute(HandDataset([hand]))
                self.assertEqual((result["spot_count"], result["hand_count"]), (0, 0))
                self.assertFalse(hand_matches_call_options(hand, {}))
        # Once Hero answers an action, an unopposed repeated call cannot reuse it.
        hand = make_hand(call_line() + [action("Hero", "call")])
        self.assertEqual(len(extract_hero_call_spots(hand)), 1)

    def test_multiway_last_aggressor_and_player_count_at_call(self):
        for middle, actor, facing, count in (
            ("call", "Villain", "bet", 3),
            ("fold", "Villain", "bet", 2),
            ("raise", "SB", "raise", 3),
        ):
            with self.subTest(middle=middle):
                hand = make_hand([action("Villain", "bet"), action("SB", middle, amount=80),
                                  action("Hero", "call", amount=10)], others=("SB",))
                spot, = extract_hero_call_spots(hand)
                self.assertEqual((spot.aggressor, spot.facing_action, spot.player_count), (actor, facing, count))
                self.assertEqual(spot.size_pct, 80 if middle == "raise" else 50)
                for selected, expected in ((["2"], count == 2), (["3+"], count == 3), (["2", "3+"], True), ([], False)):
                    self.assertEqual(hand_matches_call_options(hand, {"player_counts": selected}), expected)

    def test_size_boundaries_use_opponent_amount_and_pot(self):
        categories = ["small", "medium", "large", "overbet"]
        for size, bucket in ((40, "small"), (40.01, "medium"), (60, "medium"), (60.01, "large"),
                             (75, "large"), (99, "large"), (99.01, "overbet"), (100, "overbet"), (150, "overbet")):
            with self.subTest(size=size):
                # A short all-in call has a different amount and a later pot.
                hand = make_hand([action("Villain", "raise", amount=size), action("Hero", "call", amount=5, pot=100 + size)])
                self.assertEqual(extract_hero_call_spots(hand)[0].size_pct, size)
                for selection in ([key] for key in categories):
                    options = {"sizes": selection}
                    self.assertEqual(self.metric.compute(HandDataset([hand]), options)["spot_count"], int(bucket in selection))
                    self.assertEqual(hand_matches_call_options(hand, options), bucket in selection)
                self.assertEqual(self.metric.compute(HandDataset([hand]), {"sizes": categories})["spot_count"], 1)
                self.assertFalse(hand_matches_call_options(hand, {"sizes": []}))

    def test_streets_and_multiple_calls_per_hand(self):
        streets = ("preflop", "flop", "turn", "river")
        hand = make_hand([act for street in streets for act in call_line(street, "raise" if street == "preflop" else "bet")])
        for selected, expected in ((["ALL"], 4), (list(streets), 4), *[([s], 1) for s in streets]):
            with self.subTest(streets=selected):
                result = self.metric.compute(HandDataset([hand]), {"streets": selected})
                self.assertEqual((result["spot_count"], result["hand_count"]), (expected, 1))
        same_street = make_hand(call_line() + call_line(kind="raise"))
        result = self.metric.compute(HandDataset([same_street]))
        self.assertEqual((result["spot_count"], result["hand_count"]), (2, 1))
        self.assertEqual(result["facing_raise"], {"count": 1, "pct": 50.0})
        self.assertTrue(hand_matches_call_options(hand, {"street": "river"}))

    def test_relative_and_exact_positions_with_9max_fallback(self):
        hands = [make_hand(hero=hero, opponent=opp, hand_id=f"{hero}-{opp}")
                 for hero, opp in (("BTN", "BB"), ("BB", "BTN"), ("CO", "BB"))]
        for hand in hands:
            spot, = extract_hero_call_spots(hand)
            self.assertEqual(f"{spot.hero_position}-{spot.opponent_position}", hand.hand_id)
        selections = (
            ({"hero_positions": ["BTN"], "opponent_positions": ["BB"]}, {"BTN-BB"}),
            ({"hero_positions": ["BB"], "opponent_positions": ["BTN"]}, {"BB-BTN"}),
            ({"hero_positions": ["BTN", "CO"], "opponent_positions": ["BB"]}, {"BTN-BB", "CO-BB"}),
            ({"hero_positions": []}, set()),
            ({"opponent_positions": []}, set()),
            ({"positions": ["IP"]}, {"BTN-BB", "CO-BB"}),
            ({"positions": ["OOP"]}, {"BB-BTN"}),
            ({"positions": ["OTHER"]}, set()),
            ({"hero_positions": ["BTN"], "opponent_positions": ["BB"], "positions": ["OOP"]}, {"BTN-BB"}),
        )
        for filters, expected in selections:
            with self.subTest(filters=filters):
                options = {"player_counts": ["2"], **filters}
                self.assertEqual({h.hand_id for h in hands if hand_matches_call_options(h, options)}, expected)
                self.assertEqual(self.metric.compute(HandDataset(hands), options)["hand_count"], len(expected))
        for hero, others, expected in (("BTN", (), "IP"), ("SB", (), "OOP"), ("CO", ("BTN",), "OTHER")):
            for max_players in (6, 9):
                with self.subTest(hero=hero, max_players=max_players):
                    hand = make_hand(hero=hero, others=others, max_players=max_players)
                    opts = {"player_counts": ["2", "3+"] if others else ["2"], "positions": [expected]}
                    if max_players == 9 or others:
                        opts.update(hero_positions=["UTG"], opponent_positions=["HJ"])
                        self.assertIsNone(extract_hero_call_spots(hand)[0].hero_position)
                    self.assertTrue(hand_matches_call_options(hand, opts))
        unresolved = replace(hands[0], button_seat=None)
        self.assertFalse(hand_matches_call_options(unresolved, {"player_counts": ["2"], "hero_positions": ["BTN"]}))

    def test_flop_detail_uses_all_existing_texture_keys(self):
        for board in (("As", "7h", "2h"), ("8s", "9s", "Ts"), ("2h", "2d", "6c")):
            hand = replace(make_hand(call_line("preflop", "raise") + call_line() + call_line("turn") + call_line("river")), flop_cards=board)
            texture = classify_flop(board)
            for key in FLOP_FILTER_KEYS:
                for want in (True, False):
                    with self.subTest(board=board, key=key, want=want):
                        options = {"flop_detail": True, "flop_textures": {key: want}}
                        expected = 3 if getattr(texture, key) == want else 0
                        self.assertEqual(self.metric.compute(HandDataset([hand]), options)["spot_count"], expected)
                        self.assertEqual(hand_matches_call_options(hand, options), bool(expected))
            self.assertFalse(hand_matches_call_options(hand, {"flop_detail": True, "streets": ["preflop"]}))
        missing_board = replace(make_hand(), flop_cards=())
        self.assertFalse(hand_matches_call_options(missing_board, {"flop_detail": True, "flop_textures": {"has_ace": True}}))

    def test_turn_detail_keeps_wir_flop_line_semantics(self):
        flop_lines = {
            "flop_checkcheck": [action("Villain", "check"), action("Hero", "check")],
            "flop_call": call_line(),
            "flop_raise": [action("Hero", "bet"), action("Villain", "call")],
        }
        for label, flop in flop_lines.items():
            hand = make_hand(flop + call_line("turn") + call_line("river"))
            self.assertEqual(classify_flop_to_turn(hand), label)
            for selected in flop_lines:
                opts = {"turn_detail": True, "turn_flop_lines": [selected]}
                self.assertEqual(self.metric.compute(HandDataset([hand]), opts)["spot_count"], 2 if selected == label else 0)
                self.assertEqual(hand_matches_call_options(hand, opts), selected == label)
            for street, expected in (("preflop", 0), ("flop", 0), ("turn", 1), ("river", 1)):
                self.assertEqual(self.metric.compute(HandDataset([hand]), {"turn_detail": True, "streets": [street]})["spot_count"], expected)
        # WIR's definition excludes a Hero flop call followed by another player's call.
        multiway = make_hand(call_line() + [action("SB", "call")] + call_line("turn"), others=("SB",))
        self.assertIsNone(classify_flop_to_turn(multiway))
        self.assertFalse(hand_matches_call_options(multiway, {"turn_detail": True, "turn_flop_lines": ["flop_call"]}))

    def test_showdown_denominator_unknowns_and_hand_deduplication(self):
        triple = make_hand(call_line() + call_line("turn") + call_line("river"), cards={"Villain": ("As", "Kh")})
        options = {"player_counts": ["2"]}
        result = self.metric.compute(HandDataset([triple]), options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (3, 1))
        self.assertEqual(sum(c["count"] for c in result["opponent_showdown_grid"]["cells"]), 1)
        hands = [triple, make_hand(hand_id="suited", cards={"Villain": ("As", "Ks")}),
                 make_hand(hand_id="unknown"), make_hand(hand_id="invalid", cards={"Villain": ("As", "As")})]
        result = self.metric.compute(HandDataset(hands), options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (6, 4))
        grid = result["opponent_showdown_grid"]
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (4, 2))
        cells = {c["hand"]: c for c in grid["cells"]}
        self.assertEqual(len(cells), 169)
        self.assertEqual(cells["AKo"], {"hand": "AKo", "count": 1, "pct": 25.0})
        self.assertEqual(cells["AKs"], {"hand": "AKs", "count": 1, "pct": 25.0})
        self.assertEqual(sum(c["count"] for c in cells.values()), 2)
        pair = self.metric.compute(HandDataset([make_hand(cards={"Villain": ("Ah", "Ad")})]), options)
        self.assertEqual(pair["opponent_showdown_grid"]["cells"][0], {"hand": "AA", "count": 1, "pct": 100.0})
        empty = self.metric.compute(HandDataset(hands), {**options, "sizes": []})["opponent_showdown_grid"]
        self.assertEqual((empty["total_hands"], empty["revealed_hands"]), (0, 0))
        self.assertTrue(all(c["count"] == 0 and c["pct"] == 0 for c in empty["cells"]))
        for players in ([], ["3+"], ["2", "3+"]):
            self.assertEqual(self.metric.compute(HandDataset(hands), {"player_counts": players})["opponent_showdown_grid"],
                             {"supported": False, "reason": "heads_up_only"})

    def test_showdown_tracks_matching_aggressor_after_multiway_reraise(self):
        hand = make_hand(call_line() + [action("SB", "raise", amount=90), action("Villain", "fold"),
                                      action("Hero", "call")], others=("SB",),
                         cards={"Villain": ("Ah", "Ad"), "SB": ("As", "Kh"), "Hero": ("Qc", "Qd")})
        self.assertEqual([(s.aggressor, s.player_count) for s in extract_hero_call_spots(hand)], [("Villain", 3), ("SB", 2)])
        options = {"player_counts": ["2"], "hero_positions": ["BTN"], "opponent_positions": ["SB"], "sizes": ["large"]}
        result = self.metric.compute(HandDataset([hand]), options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (1, 1))
        self.assertEqual([c for c in result["opponent_showdown_grid"]["cells"] if c["count"]],
                         [{"hand": "AKo", "count": 1, "pct": 100.0}])
        self.assertEqual(get_replay(HandDataset([hand]), "when_i_call", 0, options)["total"], 1)

    def test_generic_metric_api_and_replay_share_global_and_spot_filters(self):
        load_builtin_metrics()
        self.assertIsInstance(get_metric("when_i_call"), WhenICallMetric)
        base = make_hand(call_line() + call_line("turn") + call_line("river"))
        dataset = HandDataset([base, replace(base, hand_id="other-stakes", stakes="1/2"),
                               replace(base, hand_id="other-date", datetime=datetime(2026, 9, 1)),
                               replace(base, hand_id="other-format", max_players=9),
                               replace(base, hand_id="other-type", table_name="RushAndCash"),
                               make_hand([], hand_id="no-call")])
        svc = AnalysisService("/tmp")
        svc._dataset = dataset
        options = {"player_counts": ["2"], "hero_positions": ["BTN"], "opponent_positions": ["BB"], "sizes": ["medium"]}
        body = {"table_format": "6max", "stakes": ["0.5/1"], "date_from": "2026-09-12", "date_to": "2026-09-12",
                "game_types": ["nlh"], "options": options}

        def post(path, payload):
            raw = json.dumps(payload).encode()
            handler = SimpleNamespace(headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw))
            with patch("app.get_service", return_value=svc):
                status, data, _ = app._handle_api("POST", path, handler)
            self.assertEqual(status, 200)
            return json.loads(data)

        result = post("/api/metrics/when_i_call", body)
        replay = post("/api/replay/hand", {**body, "source": "when_i_call", "index": 0})
        self.assertEqual((result["spot_count"], result["hand_count"], replay["total"]), (3, 1, 1))
        self.assertEqual(replay["hand"]["hand_id"], base.hand_id)
        self.assertEqual(replay["hand"]["table_format"], "6max")
        for opts in (options, {**options, "streets": ["river"]}, {**options, "sizes": ["small"]}):
            expected = self.metric.compute(dataset, opts)["hand_count"]
            self.assertEqual(get_replay(dataset, "when_i_call", 0, opts)["total"], expected)
            self.assertEqual(sum(matcher_for("when_i_call", opts)(hand) for hand in dataset.hands), expected)

    def test_gg_and_coinpoker_parser_actions_work_without_changes(self):
        for site, header, currency in (
            ("gg", "Poker Hand #GG-CALL: Hold'em No Limit ($0.50/$1) - 2026/09/12 12:00:00", "$"),
            ("cp", "CoinPoker Hand #CP-CALL: NLH (₮0.50/₮1) 2026/09/12 12:00:00 EDT", "₮"),
        ):
            with self.subTest(site=site):
                raw = f"""{header}
Table 'Call Test' 6-max Seat #1 is the button
Seat 1: Hero ({currency}100 in chips)
Seat 2: Small ({currency}100 in chips)
Seat 3: Villain ({currency}100 in chips)
Small: posts small blind {currency}0.50
Villain: posts big blind {currency}1
*** HOLE CARDS ***
Dealt to Hero [Qc Jd]
Hero: calls {currency}1
Small: folds
Villain: raises {currency}3 to {currency}4
Hero: calls {currency}3
*** FLOP *** [2c 3d 4h]
Villain: bets {currency}4
Hero: calls {currency}4
*** TURN *** [2c 3d 4h] [8s]
Villain: checks
Hero: bets {currency}4
Villain: raises {currency}8 to {currency}12
Hero: calls {currency}8
*** SHOWDOWN ***
Villain: shows [As Kh]
*** SUMMARY ***
Total pot {currency}40.50 | Rake {currency}0
Board [2c 3d 4h 8s]
"""
                hand = parse_hand(raw, source_file=f"{site}.txt")
                self.assertIsNotNone(hand)
                spots = extract_hero_call_spots(hand)
                self.assertEqual([s.facing_action for s in spots], ["raise", "bet", "raise"])
                self.assertEqual([s.size_pct for s in spots], [120.0, round(400 / 8.5, 4), round(1200 / 20.5, 4)])
                result = self.metric.compute(HandDataset([hand]), {"player_counts": ["2"]})
                self.assertEqual((result["spot_count"], result["hand_count"]), (3, 1))
                self.assertEqual(result["facing_raise"], {"count": 2, "pct": 66.67})
                self.assertEqual(result["opponent_showdown_grid"]["revealed_hands"], 1)
                # WIC keeps the original caller hand and all expectations above.
                # Its non-PFA preflop context is now ineligible for WIR.
                self.assertEqual(WhenIRaiseMetric().compute(HandDataset([hand]))["spot_count"], 0)
                # Check the same turn response with separate eligible WIR context.
                wir_hand = replace(hand, actions=[
                    act for act in hand.actions if act.street == "preflop" and act.action == "fold"
                ] + [
                    action("Hero", "raise", "preflop", amount=4, pot=1.5),
                    action("Villain", "call", "preflop", amount=3, pot=5.5),
                ] + [act for act in hand.actions if act.street != "preflop"])
                wir = WhenIRaiseMetric().compute(HandDataset([wir_hand]))
                self.assertEqual(wir["spot_count"], 1)
                self.assertEqual(wir["reraise"], {"count": 1, "pct": 100.0})


if __name__ == "__main__":
    unittest.main()
