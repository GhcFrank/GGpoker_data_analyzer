import unittest
from dataclasses import replace
from datetime import datetime

from poker.metrics.when_i_raise import (
    POT_TYPE_IDS, SIZE_IDS, WhenIRaiseMetric, classify_preflop_aggressor_context,
    extract_hero_raise_spots, hand_allowed_for_when_i_raise, hand_matches_raise_options,
)
from poker.models import Action, Hand, HandDataset
from poker.parser import parse_hand
from poker.positions.six_max import POSITION_ORDER
from poker.replay.service import get_replay
from tests.test_when_i_call import action, make_hand


def preflop_line(raisers):
    actions = [Action("preflop", player, "raise", amount=3 * (i + 1), pot_before=1.5 + 3 * i,
                      is_hero=player == "Hero") for i, player in enumerate(raisers)]
    if raisers:
        caller = "Villain" if raisers[-1] == "Hero" else "Hero"
        actions.append(Action("preflop", caller, "call", amount=3, is_hero=caller == "Hero"))
    return actions


def with_open_raise(hand):
    """Add eligible preflop context without changing the postflop case under test."""
    index = next((i for i, act in enumerate(hand.actions) if act.street != "preflop"), len(hand.actions))
    return replace(hand, went_to_flop=True,
                   actions=hand.actions[:index] + preflop_line(["Hero"]) + hand.actions[index:])


class WhenIRaiseTests(unittest.TestCase):
    def test_size_boundaries_and_general_selection(self) -> None:
        categories = ["small", "medium", "large", "overbet"]
        cases = (
            (20, "small"), (40, "small"),
            (40.01, "medium"), (50, "medium"), (60, "medium"),
            (60.01, "large"), (75, "large"), (99, "large"),
            (99.01, "overbet"), (100, "overbet"), (110, "overbet"), (150, "overbet"),
            # General must bypass size matching, including nonpositive sizes.
            (0, None),
        )
        metric = WhenIRaiseMetric()
        for size, category in cases:
            with self.subTest(size=size):
                hand = Hand(
                    hand_id="size-filter", datetime=datetime(2026, 9, 7),
                    table_name="Size filter", stakes="0.5/1", max_players=2,
                    hero_seat=1, hero_cards=None, hero_invested=0, hero_collected=0,
                    hero_returned=0, total_pot=0, rake=0, jackpot=0, bingo=0,
                    fortune=0, tax=0, source_file="size-filter.txt", button_seat=1,
                    seat_names={1: "Hero", 2: "Villain"},
                    actions=[
                        Action("flop", "Hero", "bet", amount=size, pot_before=100, is_hero=True),
                        Action("flop", "Villain", "fold"),
                    ],
                )
                hand = with_open_raise(hand)
                dataset = HandDataset([hand])
                general = metric.compute(dataset)
                self.assertEqual(general["spot_count"], 1)
                self.assertEqual(general["options"]["sizes"], list(SIZE_IDS))
                bet_general = metric.compute(dataset, {"sizes": categories})
                self.assertEqual(
                    {key: bet_general[key] for key in ("spot_count", "hand_count", "all_fold", "call", "reraise")},
                    {key: general[key] for key in ("spot_count", "hand_count", "all_fold", "call", "reraise")},
                )
                selections = [[key] for key in categories] + [
                    ["small", "medium"], ["large", "overbet"], categories, ["check"], [],
                ]
                for selected in selections:
                    with self.subTest(selected=selected):
                        matches = selected == categories or category in selected
                        options = {"sizes": selected}
                        result = metric.compute(dataset, options)
                        self.assertEqual(result["spot_count"], int(matches))
                        self.assertEqual(result["hand_count"], int(matches))
                        self.assertEqual(hand_matches_raise_options(hand, options), matches)

    def test_check_branch_uses_real_order_distinct_spots_and_separate_denominators(self):
        def check_spots(actions, *, others=()):
            hand = make_hand(preflop_line(["Hero"]) + actions, others=others)
            return hand, [spot for spot in extract_hero_raise_spots(hand)
                          if spot.action_kind == "check"]

        check_hand, spots = check_spots([action("Hero", "check"), action("Villain", "check")])
        self.assertEqual(len(spots), 1)
        self.assertEqual((spots[0].size_pct, spots[0].opponent_check, spots[0].opponent_bet),
                         (None, True, False))
        self.assertEqual((spots[0].player_count, spots[0].hero_position,
                          spots[0].opponent_position), (2, "BTN", "BB"))

        for tail in (
            [action("Villain", "bet")],
            [action("Villain", "bet"), action("Hero", "call")],
        ):
            with self.subTest(tail=[act.action for act in tail]):
                _, spots = check_spots([action("Hero", "check"), *tail])
                self.assertEqual(len(spots), 1)
                self.assertTrue(spots[0].opponent_bet)

        _, last_to_act = check_spots([action("Villain", "check"), action("Hero", "check")])
        self.assertEqual(last_to_act, [])

        for responses, outcome in (
            ([action("SB", "check"), action("Villain", "check")], "opponent_check"),
            ([action("SB", "check"), action("Villain", "bet")], "opponent_bet"),
            ([action("SB", "bet"), action("Villain", "raise")], "opponent_bet"),
        ):
            with self.subTest(responses=[act.action for act in responses]):
                _, spots = check_spots([action("Hero", "check"), *responses], others=("SB",))
                self.assertEqual(len(spots), 1)
                self.assertEqual(spots[0].player_count, 3)
                self.assertTrue(getattr(spots[0], outcome))

        mixed = make_hand(preflop_line(["Hero"]) + [
            action("Hero", "check"), action("Villain", "bet"),
            action("Hero", "raise", amount=33), action("Villain", "call"),
        ], hand_id="check-then-small-raise", cards={"Villain": ("As", "Kh")})
        metric = WhenIRaiseMetric()
        mixed_result = metric.compute(HandDataset([mixed]), {"sizes": ["check", "small"]})
        self.assertEqual((mixed_result["spot_count"], mixed_result["hand_count"]), (2, 1))
        self.assertEqual(mixed_result["call"], {"count": 1, "pct": 100.0})
        self.assertEqual(mixed_result["opponent_bet"], {"count": 1, "pct": 100.0})
        aggression_only = metric.compute(HandDataset([mixed]), {"sizes": ["small"]})
        self.assertEqual((aggression_only["spot_count"], aggression_only["call"]["pct"]), (1, 100.0))
        self.assertEqual(aggression_only["opponent_bet"], {"count": 0, "pct": None})
        check_only = metric.compute(HandDataset([mixed]), {"sizes": ["check"]})
        self.assertEqual((check_only["spot_count"], check_only["opponent_bet"]["pct"]), (1, 100.0))
        self.assertEqual(check_only["call"], {"count": 0, "pct": None})

        turn = make_hand(preflop_line(["Hero"]) + [
            action("Hero", "check"), action("Villain", "check"),
            action("Hero", "check", "turn"), action("Villain", "bet", "turn"),
        ], hand_id="turn-check", cards={"Villain": ("As", "Kh")})
        turn_options = {
            "sizes": ["check"], "streets": ["turn"], "turn_detail": True,
            "turn_flop_lines": ["flop_checkcheck"], "player_counts": ["2"],
            "hero_positions": ["BTN"], "opponent_positions": ["BB"],
        }
        turn_result = metric.compute(HandDataset([turn]), turn_options)
        self.assertEqual(turn_result["opponent_bet"], {"count": 1, "pct": 100.0})
        texture_result = metric.compute(HandDataset([check_hand]), {
            "sizes": ["check"], "flop_detail": True,
            "flop_textures": {"has_ace": True},
        })
        self.assertEqual(texture_result["spot_count"], 1)

        dataset = HandDataset([check_hand, mixed, turn])
        self.assertEqual(get_replay(dataset, "when_i_raise", 0, {
            "sizes": ["check"], "replay_outcome": "opponent_check",
        })["total"], 2)
        opponent_bet_replay = get_replay(dataset, "when_i_raise", 0, {
            "sizes": ["check"], "replay_outcome": "opponent_bet",
        })
        self.assertEqual(opponent_bet_replay["total"], 2)
        grid = metric.compute(HandDataset([mixed]), {
            "sizes": ["check"], "player_counts": ["2"],
        })["opponent_showdown_grid"]
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (1, 1))
        self.assertEqual(next(cell for cell in grid["cells"] if cell["hand"] == "AKo")["pct"], 100.0)

    def test_opponent_grid_counts_matching_heads_up_hands(self) -> None:
        base = Hand(
            hand_id="known", datetime=datetime(2026, 9, 7),
            table_name="Showdown grid", stakes="0.5/1", max_players=3,
            hero_seat=1, hero_cards=None, hero_invested=0, hero_collected=0,
            hero_returned=0, total_pot=0, rake=0, jackpot=0, bingo=0,
            fortune=0, tax=0, source_file="grid.txt", button_seat=1,
            seat_names={1: "Hero", 2: "Villain", 3: "Folded"},
            actions=[
                Action("preflop", "Folded", "fold"),
                Action("flop", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
                Action("flop", "Villain", "call", amount=50),
            ],
        )
        hands = []
        for i in range(10):
            cards = {"Folded": ("Qd", "Qs"), "Hero": ("Ac", "Ad")}
            if i < 2:
                cards["Villain"] = ("As", "Ks")
            elif i == 2:
                cards["Villain"] = ("Ah", "Qc")
            elif i == 3:
                cards["Villain"] = ("As", "As")  # Unusable cards stay unassigned.
            hands.append(replace(base, hand_id=str(i), shown_cards=cards))
        hands[0] = replace(hands[0], actions=base.actions + [
            Action("turn", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
            Action("turn", "Villain", "fold"),
        ])
        # These revealed hands must not enter the heads-up/Medium grid.
        hands.append(replace(base, hand_id="multiway", actions=base.actions[1:],
                             shown_cards={"Villain": ("Qd", "Qs")}))
        hands.append(replace(base, hand_id="overbet", shown_cards={"Villain": ("Qd", "Qs")},
                             actions=[base.actions[0], replace(base.actions[1], amount=150)]))
        dataset = HandDataset([with_open_raise(hand) for hand in hands])
        metric = WhenIRaiseMetric()
        options = {"player_counts": ["2"], "sizes": ["medium"]}
        result = metric.compute(dataset, options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (11, 10))
        self.assertEqual(result["all_fold"], {"count": 1, "pct": 9.09})
        self.assertEqual(result["call"], {"count": 10, "pct": 90.91})
        self.assertEqual(result["reraise"], {"count": 0, "pct": 0.0})
        grid = result["opponent_showdown_grid"]
        self.assertTrue(grid["supported"])
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (10, 3))
        cells = {cell["hand"]: cell for cell in grid["cells"]}
        self.assertEqual(len(cells), 169)
        self.assertEqual([grid["cells"][i]["hand"] for i in (0, 1, 13, 14, 168)],
                         ["AA", "AKs", "AKo", "KK", "22"])
        self.assertEqual({key: cell for key, cell in cells.items() if cell["count"]}, {
            "AKs": {"hand": "AKs", "count": 2, "pct": 20.0},
            "AQo": {"hand": "AQo", "count": 1, "pct": 10.0},
        })
        empty = metric.compute(dataset, {**options, "streets": ["river"]})["opponent_showdown_grid"]
        self.assertTrue(empty["supported"])
        self.assertEqual((empty["total_hands"], empty["revealed_hands"]), (0, 0))
        self.assertEqual(len(empty["cells"]), 169)
        self.assertTrue(all(cell["count"] == 0 and cell["pct"] == 0 for cell in empty["cells"]))
        for selection, spot_count, hand_count in ((None, 12, 11), (["3+"], 1, 1),
                                                  (["2", "3+"], 12, 11), ([], 0, 0)):
            with self.subTest(selection=selection):
                opts = {"sizes": ["medium"]}
                if selection is not None:
                    opts["player_counts"] = selection
                result = metric.compute(dataset, opts)
                self.assertEqual((result["spot_count"], result["hand_count"]), (spot_count, hand_count))
                self.assertEqual(result["opponent_showdown_grid"],
                                 {"supported": False, "reason": "heads_up_only"})

    def test_exact_heads_up_positions_and_legacy_fallback(self) -> None:
        seats = {1: "BTN", 2: "SB", 3: "BB", 4: "UTG", 5: "HJ", 6: "CO"}
        hands = []
        for hero, opponent in (("BTN", "BB"), ("CO", "BB"), ("BTN", "SB"),
                               ("HJ", "BB"), ("BB", "BTN")):
            names = {seat: "Hero" if pos == hero else "Villain" if pos == opponent else pos
                     for seat, pos in seats.items()}
            hand = Hand(
                hand_id=f"{hero}-{opponent}", datetime=datetime(2026, 9, 7),
                table_name="Exact positions", stakes="0.5/1", max_players=6,
                hero_seat=next(seat for seat, name in names.items() if name == "Hero"),
                hero_cards=None, hero_invested=0, hero_collected=0, hero_returned=0,
                total_pot=0, rake=0, jackpot=0, bingo=0, fortune=0, tax=0,
                source_file="positions.txt", button_seat=1, seat_names=names,
                shown_cards={"Villain": ("As", "Ks")},
                actions=[Action("preflop", name, "fold") for name in names.values()
                         if name not in ("Hero", "Villain")] + [
                    Action("flop", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
                    Action("flop", "Villain", "call", amount=50),
                    Action("turn", "Hero", "bet", amount=75, pot_before=200, is_hero=True),
                    Action("turn", "Villain", "fold"),
                ],
            )
            hand = with_open_raise(hand)
            hands.append(hand)
            self.assertEqual([(s.hero_position, s.opponent_position)
                              for s in extract_hero_raise_spots(hand) if s.street != "preflop"], [(hero, opponent)] * 2)
        metric = WhenIRaiseMetric()
        all_positions = list(POSITION_ORDER)
        exact = {"hero_positions": ["BTN"], "opponent_positions": ["BB"]}
        cases = (
            (exact, {"BTN-BB"}),
            ({**exact, "hero_positions": ["CO", "BTN"]}, {"CO-BB", "BTN-BB"}),
            ({**exact, "opponent_positions": all_positions}, {"BTN-BB", "BTN-SB"}),
            ({**exact, "hero_positions": all_positions}, {"BTN-BB", "CO-BB", "HJ-BB"}),
            ({"hero_positions": all_positions, "opponent_positions": all_positions},
             {hand.hand_id for hand in hands}),
            ({"positions": ["IP"]}, {"BTN-BB", "CO-BB", "BTN-SB", "HJ-BB"}),
            ({"positions": ["OOP"]}, {"BB-BTN"}),
            ({**exact, "positions": ["OOP"]}, {"BTN-BB"}),  # Ignore the inactive legacy axis.
        )
        for filters, expected in cases:
            with self.subTest(filters=filters):
                options = {"player_counts": ["2"], **filters}
                result = metric.compute(HandDataset(hands), options)
                self.assertEqual({h.hand_id for h in hands if hand_matches_raise_options(h, options)}, expected)
                self.assertEqual((result["spot_count"], result["hand_count"]), (2 * len(expected), len(expected)))
                grid = result["opponent_showdown_grid"]
                self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (len(expected), len(expected)))
                self.assertEqual(next(c for c in grid["cells"] if c["hand"] == "AKs"),
                                 {"hand": "AKs", "count": len(expected), "pct": 100.0})
        # Exact matching uses the same street/size filters as the other statistics.
        options = {"player_counts": ["2"], **exact, "streets": ["turn"], "sizes": ["small"]}
        result = metric.compute(HandDataset(hands), options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (1, 1))
        self.assertEqual(result["all_fold"], {"count": 1, "pct": 100.0})
        multiway = replace(hands[0], actions=[a for a in hands[0].actions if a.player != "SB"])
        self.assertFalse(hand_matches_raise_options(multiway, options))
        for fallback in (replace(hands[0], max_players=9), multiway):
            with self.subTest(max_players=fallback.max_players):
                self.assertTrue(all(s.hero_position is None and s.opponent_position is None
                                    for s in extract_hero_raise_spots(fallback)))
                for relative, expected in (("IP", True), ("OOP", False)):
                    opts = {"player_counts": ["2"] if fallback.max_players == 9 else ["2", "3+"],
                            "positions": [relative], "hero_positions": ["SB"], "opponent_positions": ["HJ"]}
                    self.assertEqual(hand_matches_raise_options(fallback, opts), expected)
        unresolved = replace(hands[0], button_seat=None)
        self.assertFalse(hand_matches_raise_options(unresolved, {"player_counts": ["2"], **exact}))
        self.assertTrue(hand_matches_raise_options(unresolved, {
            "player_counts": ["2"], "hero_positions": all_positions, "opponent_positions": all_positions,
        }))

    def test_preflop_context_counts_only_raises_and_keeps_actor_independent(self):
        for count, pot_type in enumerate((None, "srp", "3bet", "4bet", "5bet", None, None)):
            for final in ("Hero", "Villain"):
                with self.subTest(count=count, final=final):
                    other = "Villain" if final == "Hero" else "Hero"
                    raisers = [final if (count - i) % 2 else other for i in range(count)]
                    # Limp, cold calls, checks, posts and postflop raises do not count.
                    actions = [action("SB", "posts small blind", "preflop"), action("SB", "call", "preflop")]
                    for raise_action in preflop_line(raisers):
                        actions.extend([raise_action, action("SB", "call", "preflop")])
                    actions += [action("SB", "check", "preflop"), action(other, "raise", "turn")]
                    context = classify_preflop_aggressor_context(make_hand(actions, others=("SB",)))
                    self.assertEqual((context.raise_count, context.pot_type), (count, pot_type))
                    self.assertEqual(context.final_aggressor, final if count else None)
                    self.assertEqual(context.hero_is_final_aggressor, bool(count and final == "Hero"))

    def test_final_pfa_eligibility_and_flop_requirement(self):
        postflop = [action("Hero", "bet"), action("Villain", "call")]
        for raisers, eligible in (
            (["Hero"], True), (["Villain", "Hero"], True),
            (["Hero", "Villain", "Hero"], True), (["Villain", "Hero", "Villain", "Hero"], True),
            (["Hero", "Villain"], False), (["Villain", "Hero", "Villain"], False),
            (["Villain"], False), ([], False), (["Hero", "Villain", "Hero", "Villain", "Hero"], False),
        ):
            with self.subTest(raisers=raisers):
                hand = make_hand(preflop_line(raisers) + postflop)
                # The generic extractor still works for non-PFA hands and preflop.
                spots = extract_hero_raise_spots(hand)
                self.assertTrue(any(s.street == "flop" for s in spots))
                self.assertEqual(sum(s.street == "preflop" for s in spots), raisers.count("Hero"))
                self.assertEqual(hand_allowed_for_when_i_raise(hand, {}), eligible)
                self.assertEqual(hand_matches_raise_options(hand, {}), eligible)
                self.assertEqual(WhenIRaiseMetric().compute(HandDataset([hand]))["spot_count"], int(eligible))
        won_preflop = replace(make_hand(preflop_line(["Hero"])[:1] + [action("Villain", "fold", "preflop")]),
                              went_to_flop=False, flop_cards=())
        self.assertFalse(hand_allowed_for_when_i_raise(won_preflop, {}))
        self.assertFalse(hand_matches_raise_options(won_preflop, {}))
        self.assertEqual(WhenIRaiseMetric().compute(HandDataset([won_preflop]))["hand_count"], 0)
        # Each normalized source of flop evidence works without parser changes.
        for evidence in ({"went_to_flop": True}, {"flop_cards": ("As", "7h", "2h")},
                         {"actions": preflop_line(["Hero"]) + postflop}):
            self.assertTrue(hand_allowed_for_when_i_raise(replace(won_preflop, **evidence), {}))

    def test_pot_type_selection_and_replay_counts(self):
        hands = []
        for count, pot_type in enumerate((*POT_TYPE_IDS, "6bet"), 1):
            raisers = ["Hero" if (count - i) % 2 else "Villain" for i in range(count)]
            postflop = [act for street in ("flop", "turn", "river")
                        for act in (action("Hero", "bet", street), action("Villain", "call", street))]
            hands.append(make_hand(preflop_line(raisers) + postflop, hand_id=pot_type))
        dataset = HandDataset(hands)
        for selected in (None, [], ["srp"], ["3bet"], ["4bet"], ["5bet"], ["srp", "4bet"], list(POT_TYPE_IDS)):
            with self.subTest(selected=selected):
                options = {} if selected is None else {"pot_types": selected}
                expected = set(POT_TYPE_IDS if selected is None else selected)
                result = WhenIRaiseMetric().compute(dataset, options)
                self.assertEqual((result["spot_count"], result["hand_count"]), (3 * len(expected), len(expected)))
                self.assertEqual(set(result["options"]["pot_types"]), expected)
                self.assertEqual({h.hand_id for h in hands if hand_matches_raise_options(h, options)}, expected)
                first = get_replay(dataset, "when_i_raise", 0, options)
                self.assertEqual(first["total"], result["hand_count"])
                self.assertEqual({get_replay(dataset, "when_i_raise", i, options)["hand"]["hand_id"]
                                  for i in range(first["total"])}, expected)

    def test_replay_outcome_filters_distinct_hands_and_preserves_overlap(self):
        mixed = make_hand(preflop_line(["Hero"]) + [
            action("Hero", "bet", "flop", 33), action("Villain", "call", "flop"),
            action("Hero", "bet", "turn", 75), action("Villain", "fold", "turn"),
        ], hand_id="call-and-fold")
        overlap = make_hand(preflop_line(["Hero"]) + [
            action("Hero", "bet", "flop", 50), action("SB", "call", "flop"),
            action("Villain", "raise", "flop", 100),
        ], hand_id="call-and-reraise", others=("SB",))
        dataset = HandDataset([mixed, overlap])

        def replay_ids(options):
            first = get_replay(dataset, "when_i_raise", 0, options)
            return {
                get_replay(dataset, "when_i_raise", index, options)["hand"]["hand_id"]
                for index in range(first["total"])
            }

        self.assertEqual(replay_ids({}), {"call-and-fold", "call-and-reraise"})
        self.assertEqual(replay_ids({"replay_outcome": "all_fold"}), {"call-and-fold"})
        self.assertEqual(replay_ids({"replay_outcome": "call"}),
                         {"call-and-fold", "call-and-reraise"})
        self.assertEqual(replay_ids({"replay_outcome": "reraise"}), {"call-and-reraise"})
        self.assertEqual(get_replay(dataset, "when_i_raise", 0,
                                    {"replay_outcome": "unknown"})["total"], 0)

    def test_target_streets_are_postflop_only_and_responses_still_belong_to_opponents(self):
        hand = make_hand(preflop_line(["Hero"]) + [
            action("Hero", "bet", "flop", 33), action("Villain", "call"),
            action("Hero", "bet", "turn", 50), action("Villain", "raise", "turn"),
            action("Hero", "call", "turn"),
            action("Hero", "bet", "river", 75), action("Villain", "fold", "river"),
        ], cards={"Villain": ("As", "Kh")})
        cases = ((["ALL"], 3), (["flop"], 1), (["turn"], 1), (["river"], 1),
                 (["preflop"], 0), (["preflop", "turn"], 1))
        for streets, expected in cases:
            opts = {"streets": streets, "player_counts": ["2"]}
            result = WhenIRaiseMetric().compute(HandDataset([hand]), opts)
            self.assertEqual((result["spot_count"], result["hand_count"]), (expected, int(expected > 0)))
            self.assertNotIn("preflop", result["options"]["streets"])
            grid = result["opponent_showdown_grid"]
            self.assertEqual(sum(c["count"] for c in grid["cells"]), int(expected > 0))
        for street, size, response in (("flop", "small", "call"), ("turn", "medium", "reraise"), ("river", "large", "all_fold")):
            opts = {"street": street, "sizes": [size]}
            result = WhenIRaiseMetric().compute(HandDataset([hand]), opts)
            self.assertEqual(result["spot_count"], 1)
            self.assertEqual(result[response], {"count": 1, "pct": 100.0})
        self.assertFalse(hand_matches_raise_options(hand, {"street": "preflop"}))
        multiway = make_hand(preflop_line(["Hero"]) + [action("Hero", "bet"), action("SB", "call"),
                                                      action("Villain", "raise")], others=("SB",))
        result = WhenIRaiseMetric().compute(HandDataset([multiway]), {"player_counts": ["3+"]})
        self.assertEqual(result["call"], {"count": 1, "pct": 100.0})
        self.assertEqual(result["reraise"], {"count": 1, "pct": 100.0})

    def test_pfa_gate_precedes_turn_detail_and_keeps_existing_flop_lines(self):
        lines = {
            "flop_checkcheck": [action("Hero", "check"), action("Villain", "check")],
            "flop_call": [action("Villain", "bet"), action("Hero", "call")],
            "flop_raise": [action("Hero", "bet"), action("Villain", "call")],
        }
        for line, flop in lines.items():
            for raisers, pot_type in ((["Hero"], "srp"), (["Villain", "Hero"], "3bet"),
                                      (["Hero", "Villain", "Hero"], "4bet"), (["Villain"], "srp")):
                with self.subTest(line=line, raisers=raisers):
                    hand = make_hand(preflop_line(raisers) + flop + [action("Hero", "bet", "turn", 75), action("Villain", "fold", "turn")])
                    opts = {"pot_types": [pot_type], "streets": ["turn"], "turn_detail": True,
                            "turn_flop_lines": [line], "sizes": ["large"]}
                    result = WhenIRaiseMetric().compute(HandDataset([hand]), opts)
                    eligible = raisers[-1] == "Hero"
                    self.assertEqual(result["all_fold"]["count"], int(eligible))
                    self.assertEqual(hand_matches_raise_options(hand, opts), eligible)
                    self.assertEqual(get_replay(HandDataset([hand]), "when_i_raise", 0, opts)["total"], int(eligible))

    def test_showdown_and_replay_apply_pot_type_with_all_spot_filters(self):
        base = make_hand(preflop_line(["Villain", "Hero"]) + [action("Hero", "bet", amount=33), action("Villain", "call")],
                         cards={"Villain": ("As", "Kh")})
        hands = [base, replace(base, hand_id="unknown", shown_cards={}),
                 make_hand(preflop_line(["Hero"]) + base.actions[-2:], hand_id="srp", cards={"Villain": ("Ah", "Ad")}),
                 make_hand(preflop_line(["Hero", "Villain"]) + base.actions[-2:], hand_id="not-pfa", cards={"Villain": ("Ah", "Ad")}),
                 replace(base, hand_id="large", actions=base.actions[:-2] + [replace(base.actions[-2], amount=75), base.actions[-1]]),
                 make_hand(preflop_line(["Villain", "Hero"]) + base.actions[-2:], hand_id="other-position", hero="BB", opponent="BTN")]
        opts = {"pot_types": ["3bet"], "streets": ["flop"], "sizes": ["small"], "player_counts": ["2"],
                "hero_positions": ["BTN"], "opponent_positions": ["BB"], "flop_detail": True, "flop_textures": {"has_ace": True}}
        result = WhenIRaiseMetric().compute(HandDataset(hands), opts)
        self.assertEqual((result["spot_count"], result["hand_count"]), (2, 2))
        grid = result["opponent_showdown_grid"]
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (2, 1))
        self.assertEqual([c for c in grid["cells"] if c["count"]], [{"hand": "AKo", "count": 1, "pct": 50.0}])
        self.assertEqual(get_replay(HandDataset(hands), "when_i_raise", 0, opts)["total"], 2)
        self.assertFalse(hand_matches_raise_options(base, {**opts, "flop_textures": {"has_ace": False}}))

    def test_parsed_gg_and_coinpoker_final_aggressor_context(self):
        for header, currency in (
            ("Poker Hand #GG-PFA: Hold'em No Limit ($0.50/$1) - 2026/09/12 12:00:00", "$"),
            ("CoinPoker Hand #CP-PFA: NLH (₮0.50/₮1) 2026/09/12 12:00:00 EDT", "₮"),
        ):
            with self.subTest(header=header):
                hand = parse_hand(f"""{header}
Table 'PFA Test' 6-max Seat #1 is the button
Seat 1: Hero ({currency}100 in chips)
Seat 2: Small ({currency}100 in chips)
Seat 3: Villain ({currency}100 in chips)
Small: posts small blind {currency}0.50
Villain: posts big blind {currency}1
*** HOLE CARDS ***
Small: folds
Villain: raises {currency}2 to {currency}3
Hero: raises {currency}6 to {currency}9
Villain: calls {currency}6
*** FLOP *** [As 7h 2h]
Villain: checks
Hero: bets {currency}5
Villain: calls {currency}5
*** SUMMARY ***
Total pot {currency}28.50 | Rake {currency}0
""")
                self.assertIsNotNone(hand)
                context = classify_preflop_aggressor_context(hand)
                self.assertEqual((context.raise_count, context.pot_type, context.final_aggressor), (2, "3bet", "Hero"))
                result = WhenIRaiseMetric().compute(HandDataset([hand]), {"pot_types": ["3bet"], "sizes": ["small"]})
                self.assertEqual((result["spot_count"], result["hand_count"]), (1, 1))
                self.assertEqual(result["call"], {"count": 1, "pct": 100.0})


if __name__ == "__main__":
    unittest.main()
