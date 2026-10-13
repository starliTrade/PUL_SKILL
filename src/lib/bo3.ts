/**
 * Best-of-three rules (audit 8.20).
 *
 * "First to two round wins" was written out literally in eight places across
 * the game page — six `targetWins: 2` literals and two `>= 2` comparisons. A
 * change to the format (best-of-five, say) would have to find all eight, and
 * missing one leaves the scoreboard and the settlement disagreeing about
 * whether the match is over.
 *
 * The server owns the authoritative rule (`api/match_engine.ROUNDS`); this is
 * the client's mirror of it.
 */

/** Round wins needed to take the match. */
export const BO3_TARGET_WINS = 2;

/** True when either side has already taken the match. */
export const bo3Decided = (userScore: number, opponentScore: number): boolean =>
  userScore >= BO3_TARGET_WINS || opponentScore >= BO3_TARGET_WINS;
