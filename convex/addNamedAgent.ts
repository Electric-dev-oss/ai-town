import { v } from 'convex/values';
import { Descriptions } from '../data/characters';
import { insertInput } from './aiTown/insertInput';
import { internalMutation } from './_generated/server';

// Adds one agent from Descriptions. Does not stop the engine or wipe stored world data.
export const add = internalMutation({
  args: { worldId: v.id('worlds'), descriptionIndex: v.number() },
  handler: async (ctx, args) => {
    if (
      !Number.isInteger(args.descriptionIndex) ||
      args.descriptionIndex < 0 ||
      args.descriptionIndex >= Descriptions.length
    ) {
      throw new Error(`descriptionIndex must be an integer from 0 to ${Descriptions.length - 1}`);
    }
    return await insertInput(ctx, args.worldId, 'createAgent', {
      descriptionIndex: args.descriptionIndex,
    });
  },
});
