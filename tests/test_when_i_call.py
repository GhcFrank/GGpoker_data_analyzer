import io
import json
import unittest
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import app
from poker.board_texture import FLOP_FILTER_KEYS, classify_flop
from poker.metrics.base import get_metric, list_metrics, load_builtin_metrics
from poker.metrics.when_i_call import (
    WhenICallMetric,
    classify_wic_flop_to_turn,
    extract_hero_call_decision_spots,
    hand_allowed_for_when_i_call,
    hand_matches_call_options,
)
from poker.metrics.when_i_call_legacy import LegacyWhenICallMetric
from poker.metrics.when_i_raise import POT_TYPE_IDS, WhenIRaiseMetric, classify_preflop_aggressor_context
from poker.models import Action, Hand, HandDataset
from poker.parser import parse_hand
from poker.replay.matchers import matcher_for
from poker.replay.service import get_replay
from poker.service import AnalysisService


def action(player, kind, street="flop", amount=50, pot=100):
    return Action(street, player, kind, amount=amount, pot_before=pot, is_hero=player == "Hero")


def call_line(street="flop", kind="bet", size=50):
    return [action("Villain", kind, street, size), action("Hero", "call", street, size, 100 + size)]


def preflop_line(raisers=("Villain",), hero_response="call"):
    actions = [action(player, "raise", "preflop", 3 + index * 3, 2 + index * 6)
               for index, player in enumerate(raisers)]
    if raisers and raisers[-1] != "Hero" and hero_response:
        actions.append(action("Hero", hero_response, "preflop", 3, 10))
    return actions


def make_hand(
    actions=None,
    *,
    hand_id="call",
    hero="BTN",
    opponent="BB",
    others=(),
    cards=None,
    max_players=6,
    preflop_actions=None,
    went_to_flop=True,
):
    positions = ("BTN", "SB", "BB", "UTG", "HJ", "CO") if max_players == 6 else (
        "BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO",
    )
    names = {i: "Hero" if pos == hero else "Villain" if pos == opponent else pos
             for i, pos in enumerate(positions, 1)}
    folds = [action(name, "fold", "preflop", 0) for name in names.values()
             if name not in {"Hero", "Villain", *others}]
    postflop = call_line() if actions is None else actions
    pre = (
        ([] if any(act.street == "preflop" for act in postflop) else preflop_line())
        if preflop_actions is None
        else preflop_actions
    )
    return Hand(
        hand_id=hand_id, datetime=datetime(2026, 9, 12), table_name="Call Test", stakes="0.5/1",
        max_players=max_players, hero_seat=next(i for i, name in names.items() if name == "Hero"),
        hero_cards="Qc Jd", hero_invested=0, hero_collected=0, hero_returned=0, total_pot=0,
        rake=0, jackpot=0, bingo=0, fortune=0, tax=0, source_file="call.txt", button_seat=1,
        seat_names=names, actions=folds + pre + postflop,
        shown_cards=cards or {}, flop_cards=("As", "7h", "2h"), went_to_flop=went_to_flop,
    )


class WhenICallTests(unittest.TestCase):
    def setUp(self):
        self.metric = WhenICallMetric()

    def test_preflop_role_pot_types_limp_and_flop_eligibility(self):
        cases = (
            ("srp", ("Villain",), True, "srp"),
            ("hero-open-call-3bet", ("Hero", "Villain"), True, "3bet"),
            ("hero-3bet-call-4bet", ("Villain", "Hero", "Villain"), True, "4bet"),
            ("hero-4bet-call-5bet", ("Hero", "Villain", "Hero", "Villain"), True, "5bet"),
            ("hero-final-srp", ("Hero",), False, "srp"),
            ("hero-final-3bet", ("Villain", "Hero"), False, "3bet"),
            ("six-bet", ("Villain", "Hero", "Villain", "Hero", "Villain"), False, None),
        )
        hands = []
        for label, raisers, eligible, pot_type in cases:
            with self.subTest(label=label):
                pre = preflop_line(raisers, "call" if raisers[-1] != "Hero" else None)
                if raisers[-1] == "Hero":
                    pre.append(action("Villain", "call", "preflop"))
                hand = make_hand(call_line(), hand_id=label, preflop_actions=pre)
                context = classify_preflop_aggressor_context(hand)
                self.assertEqual(context.pot_type, pot_type)
                self.assertEqual(hand_allowed_for_when_i_call(hand, {}), eligible)
                self.assertEqual(hand_matches_call_options(hand, {}), eligible)
                result = self.metric.compute(HandDataset([hand]))
                self.assertEqual((result["spot_count"], result["hand_count"]), (int(eligible), int(eligible)))
                hands.append(hand)

        for label, pre, eligible in (
            ("pure-limp", [action("Hero", "call", "preflop"), action("Villain", "check", "preflop")], False),
            ("limp-raise-call", [action("Hero", "call", "preflop"), action("Villain", "raise", "preflop"),
                                  action("Hero", "call", "preflop")], True),
            ("hero-fold", [action("Villain", "raise", "preflop"), action("Hero", "fold", "preflop")], False),
        ):
            with self.subTest(label=label):
                hand = make_hand(call_line(), preflop_actions=pre, went_to_flop=eligible)
                self.assertEqual(hand_allowed_for_when_i_call(hand, {}), eligible)

        won_preflop = make_hand([], preflop_actions=preflop_line(), went_to_flop=False)
        won_preflop = replace(won_preflop, flop_cards=())
        self.assertFalse(hand_allowed_for_when_i_call(won_preflop, {}))
        self.assertEqual(self.metric.compute(HandDataset([won_preflop]))["spot_count"], 0)

        dataset = HandDataset(hands)
        for selected in (None, [], ["srp"], ["3bet"], ["4bet"], ["5bet"], ["srp", "4bet"], list(POT_TYPE_IDS)):
            with self.subTest(selected=selected):
                options = {} if selected is None else {"pot_types": selected}
                expected = set(POT_TYPE_IDS if selected is None else selected)
                expected &= {"srp", "3bet", "4bet", "5bet"}
                result = self.metric.compute(dataset, options)
                self.assertEqual(result["hand_count"], len(expected))
                self.assertEqual(set(result["options"]["pot_types"]), expected)

    def test_hero_outcomes_are_mutually_exclusive(self):
        hands = [
            make_hand([action("Villain", "bet"), action("Hero", response)], hand_id=response)
            for response in ("fold", "call", "raise")
        ]
        for hand, expected in zip(hands, ("fold", "call", "raise")):
            spot, = extract_hero_call_decision_spots(hand)
            self.assertEqual((spot.aggressor, spot.facing_action, spot.hero_response),
                             ("Villain", "bet", expected))
        result = self.metric.compute(HandDataset(hands))
        self.assertEqual((result["spot_count"], result["hand_count"]), (3, 3))
        self.assertEqual(result["hero_fold"], {"count": 1, "pct": 33.33})
        self.assertEqual(result["hero_call"], {"count": 1, "pct": 33.33})
        self.assertEqual(result["hero_raise"], {"count": 1, "pct": 33.33})
        self.assertEqual(sum(result[key]["count"] for key in ("hero_fold", "hero_call", "hero_raise")),
                         result["spot_count"])
        self.assertNotIn("facing_bet", result)
        self.assertNotIn("facing_raise", result)

    def test_checked_to_hero_branch_preserves_order_donk_and_group_denominators(self):
        checked = make_hand([action("Villain", "check"), action("Hero", "check")],
                            hand_id="hero-check", cards={"Villain": ("As", "Kh")})
        spot, = extract_hero_call_decision_spots(checked)
        self.assertEqual((spot.facing_kind, spot.facing_action, spot.size_pct, spot.hero_response),
                         ("check", "check", None, "check"))
        self.assertEqual((spot.player_count, spot.hero_position, spot.opponent_position),
                         (2, "BTN", "BB"))

        bet = make_hand([action("Villain", "check"), action("Hero", "bet")], hand_id="hero-bet")
        self.assertEqual([spot.hero_response for spot in extract_hero_call_decision_spots(bet)], ["bet"])
        wrong_order = make_hand([action("Hero", "check"), action("Villain", "check")])
        donk = make_hand([action("Hero", "bet"), action("Villain", "call")])
        self.assertEqual(extract_hero_call_decision_spots(wrong_order), [])
        self.assertEqual(extract_hero_call_decision_spots(donk), [])

        for response in ("check", "bet"):
            with self.subTest(response=response):
                multiway = make_hand([
                    action("Villain", "check"), action("SB", "check"),
                    action("Hero", response),
                ], others=("SB",))
                spots = extract_hero_call_decision_spots(multiway)
                self.assertEqual(len(spots), 1)
                self.assertEqual((spots[0].facing_kind, spots[0].hero_response,
                                  spots[0].player_count), ("check", response, 3))

        aggression = make_hand([
            action("Villain", "bet"), action("SB", "call"), action("Hero", "call"),
        ], others=("SB",))
        aggression_spot, = extract_hero_call_decision_spots(aggression)
        self.assertEqual((aggression_spot.facing_kind, aggression_spot.hero_response),
                         ("aggression", "call"))

        mixed = make_hand([
            action("Villain", "check"), action("Hero", "bet"),
            action("Villain", "bet", "turn", 33), action("Hero", "call", "turn"),
        ], hand_id="checked-to-and-small", cards={"Villain": ("As", "Kh")})
        result = self.metric.compute(HandDataset([mixed]), {"sizes": ["check", "small"]})
        self.assertEqual((result["spot_count"], result["hand_count"]), (2, 1))
        self.assertEqual(result["hero_bet"], {"count": 1, "pct": 100.0})
        self.assertEqual(result["hero_call"], {"count": 1, "pct": 100.0})
        aggression_only = self.metric.compute(HandDataset([mixed]), {"sizes": ["small"]})
        self.assertEqual((aggression_only["spot_count"], aggression_only["hero_call"]["pct"]),
                         (1, 100.0))
        self.assertEqual(aggression_only["hero_bet"], {"count": 0, "pct": None})
        check_only = self.metric.compute(HandDataset([mixed]), {"sizes": ["check"]})
        self.assertEqual((check_only["spot_count"], check_only["hero_bet"]["pct"]), (1, 100.0))
        self.assertEqual(check_only["hero_call"], {"count": 0, "pct": None})

        turn = make_hand([
            action("Villain", "bet"), action("Hero", "call"),
            action("Villain", "check", "turn"), action("Hero", "bet", "turn"),
        ], hand_id="turn-checked-to")
        turn_result = self.metric.compute(HandDataset([turn]), {
            "sizes": ["check"], "streets": ["turn"], "turn_detail": True,
            "turn_flop_lines": ["flop_call"], "player_counts": ["2"],
            "hero_positions": ["BTN"], "opponent_positions": ["BB"],
        })
        self.assertEqual(turn_result["hero_bet"], {"count": 1, "pct": 100.0})
        texture_result = self.metric.compute(HandDataset([checked]), {
            "sizes": ["check"], "flop_detail": True,
            "flop_textures": {"has_ace": True},
        })
        self.assertEqual(texture_result["spot_count"], 1)

        dataset = HandDataset([checked, bet, mixed])
        self.assertEqual(get_replay(dataset, "when_i_call", 0, {
            "sizes": ["check"], "replay_outcome": "hero_check",
        })["total"], 1)
        self.assertEqual(get_replay(dataset, "when_i_call", 0, {
            "sizes": ["check"], "replay_outcome": "hero_bet",
        })["total"], 2)
        grid = self.metric.compute(HandDataset([checked]), {
            "sizes": ["check"], "player_counts": ["2"],
        })["opponent_showdown_grid"]
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (1, 1))
        self.assertEqual(next(cell for cell in grid["cells"] if cell["hand"] == "AKo")["pct"], 100.0)

    def test_replay_outcome_filters_distinct_hands_across_streets(self):
        mixed = make_hand([
            *call_line(),
            action("Villain", "bet", "turn"), action("Hero", "fold", "turn"),
        ], hand_id="call-and-fold")
        raised = make_hand([
            action("Hero", "check"), action("Villain", "bet"),
            action("Hero", "raise"), action("Villain", "call"),
        ], hand_id="raise")
        dataset = HandDataset([mixed, raised])

        def replay_ids(options):
            first = get_replay(dataset, "when_i_call", 0, options)
            return {
                get_replay(dataset, "when_i_call", index, options)["hand"]["hand_id"]
                for index in range(first["total"])
            }

        self.assertEqual(replay_ids({}), {"call-and-fold", "raise"})
        self.assertEqual(replay_ids({"replay_outcome": "hero_fold"}), {"call-and-fold"})
        self.assertEqual(replay_ids({"replay_outcome": "hero_call"}), {"call-and-fold"})
        self.assertEqual(replay_ids({"replay_outcome": "hero_raise"}), {"raise"})
        self.assertEqual(get_replay(dataset, "when_i_call", 0,
                                    {"replay_outcome": "unknown"})["total"], 0)

    def test_invalid_or_inactive_aggression_is_excluded(self):
        cases = {
            "unopposed-call": [action("Villain", "check"), action("Hero", "call")],
            "street-reset": [action("Villain", "bet"), action("Hero", "call", "turn")],
            "zero-pot": [action("Villain", "bet", pot=0), action("Hero", "call")],
            "negative-pot": [action("Villain", "raise", pot=-1), action("Hero", "call")],
            "folded-hero": [action("Hero", "fold"), action("Villain", "bet"), action("Hero", "call")],
            "folded-aggressor": [action("Villain", "bet"), action("Villain", "fold"), action("Hero", "call")],
        }
        for label, line in cases.items():
            with self.subTest(label=label):
                hand = make_hand(line)
                self.assertEqual(self.metric.compute(HandDataset([hand]))["spot_count"], 0)
                self.assertFalse(hand_matches_call_options(hand, {}))
        answered = make_hand(call_line() + [action("Hero", "call")])
        self.assertEqual(len(extract_hero_call_decision_spots(answered)), 1)
        raised = make_hand([action("Villain", "bet"), action("Hero", "raise"),
                            action("Villain", "call"), action("Hero", "call")])
        self.assertEqual([spot.hero_response for spot in extract_hero_call_decision_spots(raised)], ["raise"])

    def test_multiway_outstanding_aggressor_and_multiple_decisions(self):
        for middle, response, actor, facing, count in (
            ("call", "call", "Villain", "bet", 3),
            ("fold", "call", "Villain", "bet", 2),
            ("raise", "fold", "SB", "raise", 3),
        ):
            with self.subTest(middle=middle):
                hand = make_hand([
                    action("Villain", "bet"), action("SB", middle, amount=80),
                    action("Hero", response, amount=10),
                ], others=("SB",))
                spot, = extract_hero_call_decision_spots(hand)
                self.assertEqual((spot.aggressor, spot.facing_action, spot.player_count), (actor, facing, count))
                self.assertEqual(spot.size_pct, 80 if middle == "raise" else 50)
                for selected, expected in ((["2"], count == 2), (["3+"], count == 3),
                                           (["2", "3+"], True), ([], False)):
                    self.assertEqual(hand_matches_call_options(hand, {"player_counts": selected}), expected)

        hand = make_hand([
            action("Villain", "bet", amount=33), action("Hero", "raise", amount=90),
            action("Villain", "raise", amount=160), action("Hero", "call", amount=70),
        ])
        spots = extract_hero_call_decision_spots(hand)
        self.assertEqual([(spot.facing_action, spot.hero_response) for spot in spots],
                         [("bet", "raise"), ("raise", "call")])
        result = self.metric.compute(HandDataset([hand]))
        self.assertEqual((result["spot_count"], result["hand_count"]), (2, 1))
        self.assertEqual(result["hero_raise"]["count"], 1)
        self.assertEqual(result["hero_call"]["count"], 1)

    def test_size_boundaries_use_opponent_amount_and_pot(self):
        categories = ["small", "medium", "large", "overbet"]
        for size, bucket in ((40, "small"), (40.01, "medium"), (60, "medium"), (60.01, "large"),
                             (99, "large"), (99.01, "overbet"), (100, "overbet"), (150, "overbet")):
            with self.subTest(size=size):
                hand = make_hand([action("Villain", "raise", amount=size),
                                  action("Hero", "call", amount=5, pot=100 + size)])
                self.assertEqual(extract_hero_call_decision_spots(hand)[0].size_pct, size)
                for selection in ([key] for key in categories):
                    expected = int(bucket in selection)
                    self.assertEqual(self.metric.compute(HandDataset([hand]), {"sizes": selection})["spot_count"], expected)
                    self.assertEqual(hand_matches_call_options(hand, {"sizes": selection}), bool(expected))
        self.assertFalse(hand_matches_call_options(make_hand(), {"sizes": []}))

    def test_postflop_streets_and_multiple_spots_per_hand(self):
        hand = make_hand(call_line() + call_line("turn") + call_line("river"))
        for selected, expected in ((["ALL"], 3), (["flop", "turn", "river"], 3),
                                   (["flop"], 1), (["turn"], 1), (["river"], 1),
                                   (["preflop"], 0), (["preflop", "turn"], 1)):
            with self.subTest(streets=selected):
                result = self.metric.compute(HandDataset([hand]), {"streets": selected})
                self.assertEqual((result["spot_count"], result["hand_count"]),
                                 (expected, int(expected > 0)))
                self.assertNotIn("preflop", result["options"]["streets"])

    def test_donk_exclusion_is_street_local(self):
        lines = (
            ([action("Hero", "bet"), action("Villain", "call")], 0),
            ([action("Hero", "bet"), action("Villain", "raise"), action("Hero", "call")], 0),
            ([action("Hero", "check"), action("Villain", "bet"), action("Hero", "raise")], 1),
        )
        for line, expected in lines:
            with self.subTest(line=[act.action for act in line]):
                result = self.metric.compute(HandDataset([make_hand(line)]))
                self.assertEqual(result["spot_count"], expected)

        hand = make_hand([
            action("Hero", "bet"), action("Villain", "call"),
            action("Hero", "check", "turn"), action("Villain", "bet", "turn"),
            action("Hero", "call", "turn"),
        ], hand_id="donk-then-turn")
        self.assertEqual(self.metric.compute(HandDataset([hand]))["spot_count"], 1)
        self.assertEqual(self.metric.compute(HandDataset([hand]), {"streets": ["flop"]})["spot_count"], 0)
        self.assertEqual(self.metric.compute(HandDataset([hand]), {"streets": ["turn"]})["hero_call"]["count"], 1)
        self.assertEqual(get_replay(HandDataset([hand]), "when_i_call", 0, {"streets": ["turn"]})["total"], 1)
        self.assertEqual(get_replay(HandDataset([hand]), "when_i_call", 0, {"streets": ["flop"]})["total"], 0)
        opts = {"turn_detail": True, "turn_flop_lines": ["flop_call"], "streets": ["turn"]}
        self.assertFalse(hand_matches_call_options(hand, opts))

    def test_relative_and_exact_positions_with_9max_fallback(self):
        hands = [make_hand(hero=hero, opponent=opp, hand_id=f"{hero}-{opp}")
                 for hero, opp in (("BTN", "BB"), ("BB", "BTN"), ("CO", "BB"))]
        for hand in hands:
            spot, = extract_hero_call_decision_spots(hand)
            self.assertEqual(f"{spot.hero_position}-{spot.opponent_position}", hand.hand_id)
        selections = (
            ({"hero_positions": ["BTN"], "opponent_positions": ["BB"]}, {"BTN-BB"}),
            ({"hero_positions": ["BB"], "opponent_positions": ["BTN"]}, {"BB-BTN"}),
            ({"hero_positions": ["BTN", "CO"], "opponent_positions": ["BB"]}, {"BTN-BB", "CO-BB"}),
            ({"hero_positions": []}, set()), ({"opponent_positions": []}, set()),
            ({"positions": ["IP"]}, {"BTN-BB", "CO-BB"}),
            ({"positions": ["OOP"]}, {"BB-BTN"}), ({"positions": ["OTHER"]}, set()),
        )
        for filters, expected in selections:
            with self.subTest(filters=filters):
                options = {"player_counts": ["2"], **filters}
                self.assertEqual({hand.hand_id for hand in hands if hand_matches_call_options(hand, options)}, expected)
                self.assertEqual(self.metric.compute(HandDataset(hands), options)["hand_count"], len(expected))
        for hero, others, expected in (("BTN", (), "IP"), ("SB", (), "OOP"), ("CO", ("BTN",), "OTHER")):
            for max_players in (6, 9):
                hand = make_hand(hero=hero, others=others, max_players=max_players)
                opts = {"player_counts": ["2", "3+"] if others else ["2"], "positions": [expected]}
                if max_players == 9 or others:
                    opts.update(hero_positions=["UTG"], opponent_positions=["HJ"])
                    self.assertIsNone(extract_hero_call_decision_spots(hand)[0].hero_position)
                self.assertTrue(hand_matches_call_options(hand, opts))
        unresolved = replace(hands[0], button_seat=None)
        self.assertFalse(hand_matches_call_options(
            unresolved,
            {"player_counts": ["2"], "hero_positions": ["BTN"], "opponent_positions": ["BB"]},
        ))

    def test_flop_detail_and_wic_turn_classifier(self):
        texture_hand = replace(make_hand(call_line() + call_line("turn") + call_line("river")),
                               flop_cards=("As", "7h", "2h"))
        texture = classify_flop(texture_hand.flop_cards)
        for key in FLOP_FILTER_KEYS:
            for want in (True, False):
                options = {"flop_detail": True, "flop_textures": {key: want}}
                expected = 3 if getattr(texture, key) == want else 0
                self.assertEqual(self.metric.compute(HandDataset([texture_hand]), options)["spot_count"], expected)
        self.assertFalse(hand_matches_call_options(replace(texture_hand, flop_cards=()),
                                                   {"flop_detail": True, "flop_textures": {"has_ace": True}}))

        flop_lines = {
            "flop_checkcheck": [action("Hero", "check"), action("Villain", "check")],
            "flop_call": call_line(),
            "flop_raise": [action("Hero", "check"), action("Villain", "bet"),
                           action("Hero", "raise"), action("Villain", "call")],
            "reraised-call": [action("Villain", "bet"), action("Hero", "raise"),
                              action("Villain", "raise"), action("Hero", "call")],
            "donk": [action("Hero", "bet"), action("Villain", "call")],
        }
        expected_labels = {
            "flop_checkcheck": "flop_checkcheck", "flop_call": "flop_call",
            "flop_raise": "flop_raise", "reraised-call": "flop_call", "donk": None,
        }
        for name, flop in flop_lines.items():
            hand = make_hand(flop + call_line("turn") + call_line("river"))
            self.assertEqual(classify_wic_flop_to_turn(hand), expected_labels[name])
            for selected in ("flop_checkcheck", "flop_call", "flop_raise"):
                opts = {"turn_detail": True, "turn_flop_lines": [selected]}
                expected = 2 if selected == expected_labels[name] else 0
                self.assertEqual(self.metric.compute(HandDataset([hand]), opts)["spot_count"], expected)

    def test_showdown_denominator_deduplication_and_matching_actor(self):
        triple = make_hand(call_line() + call_line("turn") + call_line("river"),
                           cards={"Villain": ("As", "Kh")})
        hands = [triple, make_hand(hand_id="suited", cards={"Villain": ("As", "Ks")}),
                 make_hand(hand_id="unknown"), make_hand(hand_id="invalid", cards={"Villain": ("As", "As")})]
        result = self.metric.compute(HandDataset(hands), {"player_counts": ["2"]})
        self.assertEqual((result["spot_count"], result["hand_count"]), (6, 4))
        grid = result["opponent_showdown_grid"]
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (4, 2))
        cells = {cell["hand"]: cell for cell in grid["cells"]}
        self.assertEqual((cells["AKo"]["count"], cells["AKo"]["pct"]), (1, 25.0))
        self.assertEqual((cells["AKs"]["count"], cells["AKs"]["pct"]), (1, 25.0))
        self.assertEqual(sum(cell["count"] for cell in cells.values()), 2)
        pair = self.metric.compute(
            HandDataset([make_hand(cards={"Villain": ("Ah", "Ad")})]),
            {"player_counts": ["2"]},
        )
        self.assertEqual(pair["opponent_showdown_grid"]["cells"][0],
                         {"hand": "AA", "count": 1, "pct": 100.0})
        empty = self.metric.compute(
            HandDataset(hands), {"player_counts": ["2"], "sizes": []}
        )["opponent_showdown_grid"]
        self.assertEqual((empty["total_hands"], empty["revealed_hands"]), (0, 0))
        self.assertTrue(all(cell["count"] == 0 and cell["pct"] == 0 for cell in empty["cells"]))
        for players in ([], ["3+"], ["2", "3+"]):
            self.assertEqual(
                self.metric.compute(HandDataset(hands), {"player_counts": players})["opponent_showdown_grid"],
                {"supported": False, "reason": "heads_up_only"},
            )

        hand = make_hand(call_line() + [action("SB", "raise", amount=90), action("Villain", "fold"),
                                       action("Hero", "call")], others=("SB",),
                         cards={"Villain": ("Ah", "Ad"), "SB": ("As", "Kh")})
        spots = extract_hero_call_decision_spots(hand)
        self.assertEqual([(spot.aggressor, spot.player_count) for spot in spots], [("Villain", 3), ("SB", 2)])
        options = {"player_counts": ["2"], "hero_positions": ["BTN"],
                   "opponent_positions": ["SB"], "sizes": ["large"]}
        result = self.metric.compute(HandDataset([hand]), options)
        self.assertEqual([cell for cell in result["opponent_showdown_grid"]["cells"] if cell["count"]],
                         [{"hand": "AKo", "count": 1, "pct": 100.0}])

    def test_api_replay_registry_and_legacy_reference(self):
        load_builtin_metrics()
        self.assertIsInstance(get_metric("when_i_call"), WhenICallMetric)
        self.assertNotIn("when_i_call_legacy", {metric["id"] for metric in list_metrics()})
        base = make_hand(call_line() + call_line("turn") + call_line("river"))
        dataset = HandDataset([base, replace(base, hand_id="other-stakes", stakes="1/2"),
                               replace(base, hand_id="other-date", datetime=datetime(2026, 9, 1)),
                               replace(base, hand_id="other-format", max_players=9),
                               replace(base, hand_id="other-type", table_name="RushAndCash"),
                               make_hand([], hand_id="no-decision")])
        service = AnalysisService("/tmp")
        service._dataset = dataset
        options = {"pot_types": ["srp"], "player_counts": ["2"],
                   "hero_positions": ["BTN"], "opponent_positions": ["BB"], "sizes": ["medium"]}
        body = {"table_format": "6max", "stakes": ["0.5/1"], "date_from": "2026-09-12",
                "date_to": "2026-09-12", "game_types": ["nlh"], "options": options}

        def post(path, payload):
            raw = json.dumps(payload).encode()
            handler = SimpleNamespace(headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw))
            with patch("app.get_service", return_value=service):
                status, data, _ = app._handle_api("POST", path, handler)
            self.assertEqual(status, 200)
            return json.loads(data)

        result = post("/api/metrics/when_i_call", body)
        replay = post("/api/replay/hand", {**body, "source": "when_i_call", "index": 0})
        self.assertEqual((result["spot_count"], result["hand_count"], replay["total"]), (3, 1, 1))
        self.assertEqual(replay["hand"]["hand_id"], base.hand_id)
        for opts in (options, {**options, "streets": ["river"]}, {**options, "sizes": ["small"]}):
            expected = self.metric.compute(dataset, opts)["hand_count"]
            self.assertEqual(get_replay(dataset, "when_i_call", 0, opts)["total"], expected)
            self.assertEqual(sum(matcher_for("when_i_call", opts)(hand) for hand in dataset.hands), expected)

        legacy = LegacyWhenICallMetric().compute(HandDataset([base]))
        self.assertEqual((legacy["spot_count"], legacy["facing_bet"]["count"]), (4, 3))

    def test_gg_and_coinpoker_normalized_actions_without_parser_changes(self):
        for site, header, currency in (
            ("gg", "Poker Hand #GG-CALL: Hold'em No Limit ($0.50/$1) - 2026/09/12 12:00:00", "$"),
            ("cp", "CoinPoker Hand #CP-CALL: NLH (₮0.50/₮1) 2026/09/12 12:00:00 EDT", "₮"),
        ):
            with self.subTest(site=site):
                hand = parse_hand(f"""{header}
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
Hero: checks
Villain: bets {currency}4
Hero: calls {currency}4
*** TURN *** [2c 3d 4h] [8s]
Hero: checks
Villain: bets {currency}8
Hero: raises {currency}8 to {currency}16
Villain: calls {currency}8
*** SHOWDOWN ***
Villain: shows [As Kh]
*** SUMMARY ***
Total pot {currency}40.50 | Rake {currency}0
Board [2c 3d 4h 8s]
""", source_file=f"{site}.txt")
                self.assertIsNotNone(hand)
                context = classify_preflop_aggressor_context(hand)
                self.assertEqual((context.pot_type, context.final_aggressor), ("srp", "Villain"))
                spots = extract_hero_call_decision_spots(hand)
                self.assertEqual([(spot.street, spot.hero_response) for spot in spots],
                                 [("flop", "call"), ("turn", "raise")])
                result = self.metric.compute(HandDataset([hand]), {"player_counts": ["2"]})
                self.assertEqual((result["spot_count"], result["hand_count"]), (2, 1))
                self.assertEqual(result["hero_call"]["count"], 1)
                self.assertEqual(result["hero_raise"]["count"], 1)
                self.assertEqual(result["opponent_showdown_grid"]["revealed_hands"], 1)
                self.assertEqual(WhenIRaiseMetric().compute(HandDataset([hand]))["spot_count"], 0)


if __name__ == "__main__":
    unittest.main()
