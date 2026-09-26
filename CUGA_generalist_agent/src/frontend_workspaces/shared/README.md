# @uiagent/shared

This package serves as a central repository for shared TypeScript types, interfaces, utilities, and constants that are used across the **nocodeui-workspaces** projects.

## Purpose

The `@uiagent/shared` package provides a centralized location for code that needs to be shared between different projects in our monorepo, particularly between the extension and the sidepanel React application. This ensures consistency across our codebase and follows the DRY (Don't Repeat Yourself) principle.

## What should be stored here?

This package should contain:

- **TypeScript types and interfaces** that are used in multiple projects
- **Constants** that need to be consistent across projects
- **Utility functions** that provide common functionality
- **Shared configurations** that multiple packages depend on

## Project Structure

```
shared/
├── src/
│   ├── types/       # TypeScript interfaces and types
│   ├── constants/   # Shared constants and enums
│   ├── utils/       # Utility functions
│   └── index.ts     # Main export file
├── package.json
└── tsconfig.json
```

### Examples of appropriate shared content:

✅ Interface definitions for API responses and requests  
✅ Type definitions for message formats  
✅ Shared enums and constants  
✅ Common validation functions  
✅ Shared utility functions  
✅ Theme definitions and styles that should be consistent

### What should NOT be stored here:

❌ UI components (these should be in a separate UI library if needed)  
❌ Business logic specific to one project  
❌ Large dependencies that are only needed by one project  
❌ Environment-specific configuration

## Getting Started

### Installation

This package is automatically available to all projects in the monorepo through npm workspaces. You can import it in any project:

```typescript
import { JWTToken, validFileExtension } from "@uiagent/shared";
```

### Building

```bash
# From the monorepo root
npm run build -w @uiagent/shared

# Or from within the shared directory
npm run build
```

### Clean all dist

```bash
# Clean up all the dist/types from the shared directory
npm run clean
```

### Enable watch mode

```bash
# Consider enabling watch mode when adding/updating any file
npm run watch
```

## Best Practices

1. **Keep it small and focused**: Only include what's truly needed across multiple projects.
2. **Document your types when needed**: Add JSDoc comments to interfaces and types.
3. **Export everything from the index file**: Ensure all shared code is exported from `src/index.ts`.
4. **Minimize dependencies**: Keep external dependencies to a minimum.
5. **Write tests**: For utility functions and other testable code.
6. **Avoid circular dependencies**: Be careful not to create dependency cycles.
7. **Rebuild**: Rebuild the package after making changes
