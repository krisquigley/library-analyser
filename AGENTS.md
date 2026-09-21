# AGENTS.md

## Container Runtime

Use **Podman**, not Docker, for all container operations in this repository.

- Use `podman` commands for container inspection, execution, file copies, and cleanup.
- Do not invoke the `docker` CLI or assume a Docker daemon/socket is available.
- If tooling uses a Docker-compatible API or an adapter named `docker`, ensure it is configured to use Podman; the adapter name is not permission to use Docker.
- If Podman is unavailable or misconfigured, report the blocker rather than falling back to Docker.

## Development Philosophy

Agents working in this repository must practice disciplined, test-driven development and Clean Architecture.

Act as if guided by Robert C. Martin's Clean Architecture principles:

- Tests drive design.
- Business rules are independent of frameworks.
- Source code dependencies point inward.
- Boundaries are explicit and visible in the folder structure.
- Details depend on policies; policies do not depend on details.
- The domain model must not know about databases, web frameworks, queues, CLIs, file systems, or external services.

Prefer simple, explicit, boring code over clever abstractions.

## Required Workflow: TDD

For all production behavior changes, use test-driven development:

1. **Red** — write a failing test that describes the desired behavior.
2. **Green** — write the smallest production code needed to pass.
3. **Refactor** — improve names, structure, boundaries, duplication, and design while keeping tests green.

Do not write substantial production code before a failing test exists unless the task is purely mechanical, such as formatting, renaming, or moving files.

When fixing a bug:

1. Reproduce the bug with a failing test.
2. Implement the fix.
3. Keep the regression test.

When adding features:

1. Start with use-case or domain behavior tests.
2. Add interface adapter and infrastructure tests only where needed.
3. Avoid testing implementation details.

## Clean Architecture Dependency Rule

The dependency rule is mandatory:

> Source code dependencies must point inward, from details toward policies.

Outer layers may depend on inner layers. Inner layers must not depend on outer layers.

Allowed direction:

```text
Frameworks & Drivers
        ↓
Interface Adapters
        ↓
Application Use Cases
        ↓
Enterprise / Domain Entities
```

Forbidden examples:

- Domain importing database code.
- Domain importing HTTP, CLI, UI, ORM, framework, or serialization libraries.
- Use cases depending directly on concrete infrastructure.
- Application services constructing concrete gateways, repositories, or external clients.
- Tests forcing production code to expose internal details.

## Folder Structure and Boundaries

Folder structure must make architectural boundaries obvious.

Prefer this structure unless the language ecosystem strongly requires a variation:

```text
src/
  domain/
    entities/
    value_objects/
    services/
    events/
    errors/

  application/
    use_cases/
    ports/
    services/
    dto/

  interface_adapters/
    controllers/
    presenters/
    gateways/
    mappers/
    view_models/

  infrastructure/
    persistence/
    external_services/
    config/
    logging/
    filesystem/
    messaging/

  frameworks/
    web/
    cli/
    workers/
    dependency_injection/

tests/
  unit/
    domain/
    application/
  integration/
    interface_adapters/
    infrastructure/
  acceptance/
```

### Boundary Responsibilities

#### `domain/`

Contains enterprise business rules.

Allowed:
- Entities
- Value objects
- Domain services
- Domain events
- Domain-specific errors
- Pure business invariants

Forbidden:
- Database access
- HTTP clients
- Framework annotations when avoidable
- File system access
- Environment variables
- Logging frameworks
- Serialization concerns
- Dependency injection containers

#### `application/`

Contains application-specific business rules and orchestration.

Allowed:
- Use cases / interactors
- Input and output boundaries
- Ports / interfaces
- Application DTOs
- Transaction boundary abstractions

Forbidden:
- Concrete database implementations
- Concrete HTTP clients
- Framework controllers
- ORM models leaking inward
- CLI parsing
- Web request or response objects

#### `interface_adapters/`

Converts between the outside world and application/domain models.

Allowed:
- Controllers
- Presenters
- Gateways implementing application ports
- Mappers
- View models
- Request/response translation

Forbidden:
- Business rules that belong in domain or use cases
- Framework bootstrapping
- Direct policy decisions that should be in application code

#### `infrastructure/`

Contains details.

Allowed:
- Database implementations
- External API clients
- File system implementations
- Message brokers
- Logging adapters
- Configuration loading
- Concrete implementations of application ports

Forbidden:
- Domain policy
- Use-case orchestration
- Business decisions

#### `frameworks/`

Contains framework and delivery mechanisms.

Allowed:
- Web server setup
- CLI entrypoints
- Worker process setup
- Dependency injection composition root
- Routing
- Framework-specific configuration

Forbidden:
- Business rules
- Domain decisions
- Use-case logic beyond invoking the appropriate application boundary

## Dependency Injection

Use dependency inversion.

- Define ports/interfaces in `application/ports/`.
- Implement those ports in `infrastructure/` or `interface_adapters/`.
- Wire concrete implementations only at the composition root, usually in `frameworks/`.

Application and domain code must receive dependencies through constructors, function parameters, or explicit interfaces. They must not instantiate concrete infrastructure directly.

## Testing Expectations

### Domain Tests

Domain tests should be fast, isolated, and framework-free.

They should verify:
- Business invariants
- Entity behavior
- Value object validation
- Domain services
- Domain events

### Application Tests

Application tests should verify use-case behavior through ports.

Use fakes, stubs, spies, or in-memory adapters for boundaries.

They should verify:
- Use-case orchestration
- Business decisions
- Calls to output ports
- Error handling
- Transactional behavior where applicable

### Adapter and Infrastructure Tests

Adapter tests may use integration-style tests.

They should verify:
- Mapping correctness
- Persistence behavior
- External service adapter behavior
- Framework integration at the boundary

Do not let slow infrastructure tests replace fast domain and application tests.

## Design Rules

- Keep domain objects persistence-ignorant.
- Keep use cases small and focused.
- Name use cases after user/business intent.
- Avoid anemic pass-through layers, but do not collapse architectural boundaries for convenience.
- Prefer explicit mappers at boundaries.
- Do not leak ORM models, HTTP requests, JSON payloads, or framework objects into the domain or application layers.
- Keep validation close to the rule it protects.
- Treat external systems as plugins.
- Make dependencies visible.
- Avoid global state.
- Avoid hidden I/O.
- Avoid temporal coupling where possible.

## Refactoring Rules

Refactor only with tests passing unless intentionally performing a red-green-refactor step.

When moving code across boundaries:

1. Add or update tests around the intended behavior.
2. Move policy inward.
3. Move details outward.
4. Introduce ports where inward code needs outward behavior.
5. Verify dependency direction after the move.

## Agent Behavior

Before implementing:

1. Identify the use case or business rule.
2. Identify the architectural layer where the change belongs.
3. Write or update tests first.
4. Keep folder boundaries explicit.
5. Run the relevant tests.
6. Report what changed and which tests were run.

If requirements are unclear, ask for clarification before inventing architecture.

Do not introduce frameworks, databases, queues, or external services unless the task explicitly requires them or the existing project already uses them.

When creating new folders, choose names that reveal architectural intent, not technical convenience.

## Definition of Done

A change is done only when:

- The behavior is covered by tests.
- Tests pass.
- Dependencies point inward.
- Folder placement reflects Clean Architecture boundaries.
- Domain and application layers are free from framework and infrastructure details.
- Any architectural tradeoff is documented in the final response.
