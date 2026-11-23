// The saved recipe responses (#139), checked against their schemas at the boundary. A wrong shape is refused whole.

export function savedPlaylistRecipesFrom(body) {
  if (!Array.isArray(body?.recipes)) refuseSavedRecipeList('recipes must be a list');
  return body.recipes.map((row, index) => {
    const label = `recipe ${index + 1}`;
    if (typeof row?.name !== 'string') refuseSavedRecipeList(`${label} name must be text`);
    if (typeof row.updated_at !== 'string') refuseSavedRecipeList(`${label} updated_at must be text`);
    if (row.problem !== null && typeof row.problem !== 'string') refuseSavedRecipeList(`${label} problem must be text or null`);
    return {name: row.name, updatedAt: row.updated_at, problem: row.problem};
  });
}

export function savedPlaylistRecipeFrom(body) {
  if (typeof body?.name !== 'string') refuseSavedRecipe('name must be text');
  if (!body.recipe || typeof body.recipe !== 'object' || Array.isArray(body.recipe)) refuseSavedRecipe('recipe must be a JSON object');
  return {name: body.name, recipe: body.recipe};
}

function refuseSavedRecipeList(problem) {
  throw new Error(`Invalid saved recipe list: ${problem}`);
}

function refuseSavedRecipe(problem) {
  throw new Error(`Invalid saved recipe: ${problem}`);
}
