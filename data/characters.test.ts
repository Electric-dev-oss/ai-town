import { readFileSync } from 'fs';
import path from 'path';
import { Descriptions, characters } from './characters';

const FAMILY = [
  'Jolt',
  'Lyra',
  'Enrique',
  'Mira',
  'Elian Marlowe',
  'Demon Outlaw',
  'Erebus Stormvale',
];

test('Descriptions are the seven Stormvale characters', () => {
  expect(Descriptions.map((description) => description.name)).toEqual(FAMILY);
  expect(new Set(Descriptions.map((description) => description.character)).size).toBe(
    FAMILY.length,
  );
  for (const description of Descriptions) {
    expect(description.identity.length).toBeGreaterThan(0);
    expect(description.plan.length).toBeGreaterThan(0);
    expect(description.identity).not.toMatch(/\/home\/|\/Users\/|@|AKIA|sk-/);
  }
});

test('sprite sheet entries stay on the existing folk asset', () => {
  expect(characters.map((character) => character.name)).toEqual([
    'f1',
    'f2',
    'f3',
    'f4',
    'f5',
    'f6',
    'f7',
    'f8',
  ]);
  for (const character of characters) {
    expect(character.textureUrl).toBe('/ai-town/assets/32x32folk.png');
  }
});

test('addNamedAgent only enqueues createAgent', () => {
  const src = readFileSync(path.join(process.cwd(), 'convex/addNamedAgent.ts'), 'utf8');
  expect(src).toContain("insertInput(ctx, args.worldId, 'createAgent'");
  expect(src).not.toMatch(/wipeAllTables|stopAllowed|replace\(|delete\(/);
});

test('init was not turned into a world reset', () => {
  const src = readFileSync(path.join(process.cwd(), 'convex/init.ts'), 'utf8');
  expect(src).not.toMatch(/wipeAllTables/);
  expect(src).toContain('if (world.agents.length > 0)');
});
