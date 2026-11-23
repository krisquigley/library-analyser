// The saved recipe controls' commands (#139). The chosen name is validated before the use case sees it.

export function savedRecipeController({savedRecipes, rejectInput}) {
  return Object.freeze({
    listRequested: () => savedRecipes.list(),
    async loadRequested(name) {
      if (typeof name !== 'string' || !name.trim()) {
        rejectInput('Choose a saved recipe to load');
        return;
      }
      await savedRecipes.load(name);
    },
  });
}
