from collections import defaultdict, deque
import random
from typing import Optional, Tuple, cast
from risk_helper.game import Game
from risk_shared.models.card_model import CardModel
from risk_shared.queries.query_attack import QueryAttack
from risk_shared.queries.query_claim_territory import QueryClaimTerritory
from risk_shared.queries.query_defend import QueryDefend
from risk_shared.queries.query_distribute_troops import QueryDistributeTroops
from risk_shared.queries.query_fortify import QueryFortify
from risk_shared.queries.query_place_initial_troop import QueryPlaceInitialTroop
from risk_shared.queries.query_redeem_cards import QueryRedeemCards
from risk_shared.queries.query_troops_after_attack import QueryTroopsAfterAttack
from risk_shared.queries.query_type import QueryType
from risk_shared.records.moves.move_attack import MoveAttack
from risk_shared.records.moves.move_claim_territory import MoveClaimTerritory
from risk_shared.records.moves.move_defend import MoveDefend
from risk_shared.records.moves.move_distribute_troops import MoveDistributeTroops
from risk_shared.records.moves.move_fortify import MoveFortify
from risk_shared.records.moves.move_place_initial_troop import MovePlaceInitialTroop
from risk_shared.records.moves.move_redeem_cards import MoveRedeemCards
from risk_shared.records.moves.move_troops_after_attack import MoveTroopsAfterAttack
from risk_shared.records.record_attack import RecordAttack
from risk_shared.records.types.move_type import MoveType


# We will store our enemy in the bot state.
class BotState():
    def __init__(self):
        self.enemy: Optional[int] = None


def main():
    
    # Get the game object, which will connect you to the engine and
    # track the state of the game.
    game = Game()
    bot_state = BotState()
   
    # Respond to the engine's queries with your moves.
    while True:

        # Get the engine's query (this will block until you receive a query).
        query = game.get_next_query()

        # Based on the type of query, respond with the correct move.
        def choose_move(query: QueryType) -> MoveType:
            match query:
                case QueryClaimTerritory() as q:
                    return handle_claim_territory(game, bot_state, q)

                case QueryPlaceInitialTroop() as q:
                    return handle_place_initial_troop(game, bot_state, q)

                case QueryRedeemCards() as q:
                    return handle_redeem_cards(game, bot_state, q)

                case QueryDistributeTroops() as q:
                    return handle_distribute_troops(game, bot_state, q)

                case QueryAttack() as q:
                    return handle_attack(game, bot_state, q)

                case QueryTroopsAfterAttack() as q:
                    return handle_troops_after_attack(game, bot_state, q)

                case QueryDefend() as q:
                    return handle_defend(game, bot_state, q)

                case QueryFortify() as q:
                    return handle_fortify(game, bot_state, q)
        
        # Send the move to the engine.
        game.send_move(choose_move(query))
                

def handle_claim_territory(game: Game, bot_state: BotState, query: QueryClaimTerritory) -> MoveClaimTerritory:
    """At the start of the game, you can claim a single unclaimed territory every turn 
    until all the territories have been claimed by players."""

    unclaimed_territories = game.state.get_territories_owned_by(None)
    my_territories = game.state.get_territories_owned_by(game.state.me.player_id)

    # We will try to always pick new territories that are next to ones that we own,
    # or a random one if that isn't possible.
    adjacent_territories = game.state.get_all_adjacent_territories(my_territories)

    # We can only pick from territories that are unclaimed and adjacent to us.
    available = list(set(unclaimed_territories) & set(adjacent_territories))
    if len(available) == 0:
        selected_territory = random.sample(unclaimed_territories, 1)[0]
    
    # Or if there are no such territories, we will pick just an unclaimed one.
    else:
        selected_territory = random.sample(unclaimed_territories, 1)[0]

    return game.move_claim_territory(query, selected_territory)


def handle_place_initial_troop(game: Game, bot_state: BotState, query: QueryPlaceInitialTroop) -> MovePlaceInitialTroop:
    """After all the territories have been claimed, you can place a single troop on one
    of your territories each turn until each player runs out of troops."""
    
    # We will place troops along the territories on our border.
    border_territories = game.state.get_all_border_territories(
        game.state.get_territories_owned_by(game.state.me.player_id)
    )

    # We will place a troop in the border territory with the least troops currently
    # on it. This should give us close to an equal distribution.
    border_territory_models = [game.state.territories[x] for x in border_territories]
    min_troops_territory = min(border_territory_models, key=lambda x: x.troops)

    return game.move_place_initial_troop(query, min_troops_territory.territory_id)


def handle_redeem_cards(game: Game, bot_state: BotState, query: QueryRedeemCards) -> MoveRedeemCards:
    """After the claiming and placing initial troops phases are over, you can redeem any
    cards you have at the start of each turn, or after killing another player."""

    # We will always redeem the minimum card sets we can (to increase the card set bonus
    # over the whole game). We could improve this by trying to redeem sets that give us
    # the matching territory bonus, or by reducing our usage of wildcards or matching
    # territory cards after we have already received the bonus for this turn.

    # We always have to redeem enough cards to reduce our card count below five.
    card_sets: list[Tuple[CardModel, CardModel, CardModel]] = []
    cards_remaining = game.state.me.cards.copy()

    while len(cards_remaining) >= 5:
        card_set = game.state.get_card_set(cards_remaining)
        # According to the pigeonhole principle, we should always be able to make a set
        # of cards if we have at least 5 cards.
        assert card_set != None
        card_sets.append(card_set)

        cards_remaining = [card for card in cards_remaining if card not in card_set]
    
    return game.move_redeem_cards(query, [(x[0].card_id, x[1].card_id, x[2].card_id) for x in card_sets])


def handle_distribute_troops(game: Game, bot_state: BotState, query: QueryDistributeTroops) -> MoveDistributeTroops:
    """After you redeem cards (you may have chosen to not redeem any), you need to distribute
    all the troops you have available across your territories. This can happen at the start of
    your turn or after killing another player.
    """

    # We will distribute troops across our border territories.
    total_troops = game.state.me.troops_remaining
    distributions = defaultdict(lambda: 0)
    border_territories = game.state.get_all_border_territories(
        game.state.get_territories_owned_by(game.state.me.player_id)
    )

    # We need to remember we have to place our matching territory bonus
    # if we have one.
    if len(game.state.me.must_place_territory_bonus) != 0:
        assert total_troops >= 2
        distributions[game.state.me.must_place_territory_bonus[0]] += 2
        total_troops -= 2

    # If we have an enemy, we will stack troops near if they neighbour us and we feel aggressive.
    if bot_state.enemy != None and random.random() < 0.8:
        enemy_territories = set(game.state.get_territories_owned_by(bot_state.enemy))
        neighbouring_enemy = [territory for territory in border_territories if len(set(game.state.map.get_adjacent_to(territory)) & enemy_territories) != 0]

        if len(neighbouring_enemy) != 0:
            distributions[neighbouring_enemy[0]] += total_troops
            return game.move_distribute_troops(query, distributions)
        
        # If our enemy is no longer neighbouring us, we forget about them
        else:
            bot_state.enemy = None

    # Otherwise we will equally distribute across border territories.
    troops_per_territory = total_troops // len(border_territories)
    leftover_troops = total_troops % len(border_territories)
    for territory in border_territories:
        distributions[territory] += troops_per_territory

    # The leftover troops will be put some territory (we don't care)
    distributions[border_territories[0]] += leftover_troops

    return game.move_distribute_troops(query, distributions)


def handle_attack(game: Game, bot_state: BotState, query: QueryAttack) -> MoveAttack:
    """After the troop phase of your turn, you may attack any number of times until you decide to
    stop attacking (by passing). After a successful attack, you may move troops into the conquered
    territory. If you eliminated a player you will get a move to redeem cards and then distribute troops."""
    
    # We will attack someone.
    my_territories = game.state.get_territories_owned_by(game.state.me.player_id)
    bordering_territories = game.state.get_all_adjacent_territories(my_territories)

    def attack_weakest(territories: list[int]) -> Optional[MoveAttack]:
        # We will attack the weakest territory from the list for which the difference in troops between that 
        # territory and one of ours that can attack it is at least 3 in our favour.
        territories = sorted(territories, key=lambda x: game.state.territories[x].troops)
        for candidate_target in territories:
            candidate_attackers = list(set(game.state.map.get_adjacent_to(candidate_target)) & set(my_territories))
            for candidate_attacker in candidate_attackers:
                if game.state.territories[candidate_attacker].troops > game.state.territories[candidate_target].troops + 3:
                    return game.move_attack(query, candidate_attacker, candidate_target, 3)


    # We will check if anyone attacked us in the last round.
    new_records = game.state.recording[game.state.new_records:]
    enemy = None
    for record in new_records:
        match record:
            case MoveAttack() as r:
                if (r.move != "pass" and r.move.defending_territory in set(my_territories)):
                    enemy = r.move_by_player

    # If we don't have an enemy yet, or we feel angry, this player will become our enemy.
    if enemy != None:
        if bot_state.enemy == None or random.random() < 0.05:
            bot_state.enemy = enemy
    
    # If we have no enemy, we will pick the player with the weakest territory bordering us, and make them our enemy.
    else:
        weakest_territory = min(bordering_territories, key=lambda x: game.state.territories[x].troops)
        bot_state.enemy = game.state.territories[weakest_territory].occupier
        
    # We will attack their weakest territory that gives us a favourable battle if possible.
    enemy_territories = list(set(bordering_territories) & set(game.state.get_territories_owned_by(enemy)))
    move = attack_weakest(enemy_territories)
    if move != None:
        return move

    # Otherwise we will pass.
    return game.move_attack_pass(query)


def handle_troops_after_attack(game: Game, bot_state: BotState, query: QueryTroopsAfterAttack) -> MoveTroopsAfterAttack:
    """After conquering a territory in an attack, you must move troops to the new territory."""
    
    # First we need to get the record that describes the attack, and then the move that specifies
    # which territory was the attacking territory.
    record_attack = cast(RecordAttack, game.state.recording[query.record_attack_id])
    move_attack = cast(MoveAttack, game.state.recording[record_attack.move_attack_id])
    assert move_attack.move != "pass"

    # We will always move the maximum number of troops we can.
    return game.move_troops_after_attack(query, game.state.territories[move_attack.move.attacking_territory].troops - 1)


def handle_defend(game: Game, bot_state: BotState, query: QueryDefend) -> MoveDefend:
    """If you are being attacked by another player, you must choose how many troops to defend with."""

    # We will always defend with the most troops that we can.

    # First we need to get the record that describes the attack we are defending against.
    move_attack = cast(MoveAttack, game.state.recording[query.move_attack_id])
    assert move_attack.move != "pass" # Since we are defending against this attack, it can't be a pass.
    defending_territory = move_attack.move.defending_territory
    
    # We can only defend with up to 2 troops, and no more than we have stationed on the defending
    # territory.
    defending_troops = min(game.state.territories[defending_territory].troops, 2)
    return game.move_defend(query, defending_troops)


def handle_fortify(game: Game, bot_state: BotState, query: QueryFortify) -> MoveFortify:
    """At the end of your turn, after you have finished attacking, you may move a number of troops between
    any two of your territories (they must be adjacent)."""

    print("fortifying!")

    # We will always fortify towards the most powerful player (player with most troops on the map) to defend against them.
    my_territories = game.state.get_territories_owned_by(game.state.me.player_id)
    total_troops_per_player = {}
    for player in game.state.players.values():
        total_troops_per_player[player.player_id] = sum([game.state.territories[x].troops for x in game.state.get_territories_owned_by(player.player_id)])

    most_powerful_player = max(total_troops_per_player.items(), key=lambda x: x[1])[0]

    # If we are the most powerful, we will pass.
    if most_powerful_player == game.state.me.player_id:
        return game.move_fortify_pass(query)
    
    # Otherwise we will find the shortest path between our non-border territory with the most troops
    # and any of the most powerful player's territories and fortify along that path.
    candidate_territories = list(set(my_territories) - set(game.state.get_all_border_territories(my_territories)))
    
    # If there are no non-border territories we will pass.
    if len(candidate_territories) == 0:
        return game.move_fortify_pass(query)

    most_troops_territory = max(candidate_territories, key=lambda x: game.state.territories[x].troops)

    # To find the shortest path, we will use a custom function.
    shortest_path = find_shortest_path_from_vertex_to_set(game, most_troops_territory, set(game.state.get_territories_owned_by(most_powerful_player)))

    # We will move our troops along this path (we can only move one step, and we have to leave one troop behind).
    # We have to check that we can move any troops though, if we can't then we will pass our turn.
    if game.state.territories[most_troops_territory].troops > 1:
        return game.move_fortify(query, shortest_path[0], shortest_path[1], game.state.territories[most_troops_territory].troops - 1)
    else:
        return game.move_fortify_pass(query)


def find_shortest_path_from_vertex_to_set(game: Game, source: int, target_set: set[int]) -> list[int]:
    """Used in move_fortify()."""

    # We perform a BFS search from our source vertex, stopping at the first member of the target_set we find.
    queue = deque()
    queue.appendleft(source)

    parent = {}
    seen = {}

    while len(queue) != 0:
        current = queue.pop()

        if current in target_set:
            break

        for neighbour in game.state.map.get_adjacent_to(current):
            if neighbour not in seen:
                seen[neighbour] = True
                parent[neighbour] = current
                queue.appendleft(neighbour)

    path = []
    while current in parent:
        path.append(current)
        current = parent[current]

    return path[::-1]

if __name__ == "__main__":
    main()