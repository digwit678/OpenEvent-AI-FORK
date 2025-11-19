# GitHub Codespaces for Manager Demo

This document explains how to use GitHub Codespaces to run and test the OpenEvent application. This is designed for non-technical users to be able to test the application without any local setup.

## Branch Strategy

The `manager-demo` branch is a dedicated branch for the manager to test the application. This branch will always contain a stable version of the application that is ready for testing.

## How to update the `manager-demo` branch

As a developer, to update the `manager-demo` branch with the latest changes, you can use one of the following methods:

-   **Merge `main` into `manager-demo`:**
    ```bash
    git checkout manager-demo
    git pull origin manager-demo
    git merge main
    git push origin manager-demo
    ```
-   **Open a Pull Request:**
    -   Create a pull request from the `main` branch to the `manager-demo` branch.
    -   Once the pull request is reviewed and approved, merge it.

## How the manager uses Codespaces

To run and test the application, the manager should follow these steps:

1.  Navigate to the repository on GitHub: [https://github.com/your-repo/openevent-ai](https://github.com/your-repo/openevent-ai)
2.  Select the `manager-demo` branch from the branch dropdown.
3.  Click on the "Code" button, and then select the "Codespaces" tab.
4.  Click on "New on manager-demo". This will create a new Codespace and start the setup process.
5.  Wait for the Codespace to be created and for the application to start automatically. This may take a few minutes.
6.  Once the application is running, a notification will appear in the bottom right corner of the screen with a forwarded port for the frontend. Click on the URL for the "frontend" port (port 3000).
7.  The application will open in a new browser tab.

## Environment Variables and Secrets

The application requires certain environment variables and secrets to run, such as `OPENAI_API_KEY`. These should not be set by the manager inside the Codespace.

To set these secrets:

1.  Go to the repository settings on GitHub.
2.  In the "Security" section, click on "Secrets and variables", then "Codespaces".
3.  Add the required secrets (e.g., `OPENAI_API_KEY`) as repository secrets.

These secrets will be automatically available in the Codespace environment.
