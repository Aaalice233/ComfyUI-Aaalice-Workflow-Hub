export type PublishRepository = {
  full_name: string;
  name?: string;
  owner?: string;
  description?: string;
};

export function publishRepositoryUrl(repository: PublishRepository): string {
  return `https://github.com/${repository.full_name}`;
}

function findRepositoryUrl(repositories: PublishRepository[], candidate: string): string {
  const normalizedCandidate = candidate.trim().replace(/\/+$/, "").toLocaleLowerCase();
  if (!normalizedCandidate) return "";
  const repository = repositories.find(
    (item) => publishRepositoryUrl(item).toLocaleLowerCase() === normalizedCandidate
  );
  return repository ? publishRepositoryUrl(repository) : "";
}

export function resolvePublishRepositoryUrl(
  repositories: PublishRepository[],
  current: string,
  remembered: string
): string {
  return findRepositoryUrl(repositories, current)
    || findRepositoryUrl(repositories, remembered)
    || (repositories[0] ? publishRepositoryUrl(repositories[0]) : "");
}
