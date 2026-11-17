import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Layout } from "../src/components/Layout.tsx";
import { RequireRole } from "../src/components/RequireRole.tsx";
import { MyDonations } from "../src/pages/MyDonations.tsx";
import { SignIn } from "../src/pages/SignIn.tsx";
import { fail, fakeBackend, ok, renderApp, signedIn } from "./helpers.tsx";

describe("sessions and roles", () => {
  it("an expired token signs the person out with an explanation", async () => {
    signedIn("donor");
    const { fetchImpl } = fakeBackend({ "GET /api/v1/me/donations": fail(401, "TOKEN_EXPIRED") });
    renderApp(<RequireRole><MyDonations /></RequireRole>, { route: "/account/donations", fetchImpl });
    expect(await screen.findByText("Sign-in page")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("fundbridge.session")).toBeNull();
  });

  it("signed-out visitors are sent to sign in", async () => {
    const { fetchImpl } = fakeBackend({});
    renderApp(<RequireRole roles={["reviewer"]}><p>Desk</p></RequireRole>, { route: "/review", fetchImpl });
    expect(await screen.findByText("Sign-in page")).toBeInTheDocument();
  });

  it("the wrong role sees an explanation, not the screen", async () => {
    signedIn("donor");
    const { fetchImpl } = fakeBackend({});
    renderApp(<RequireRole roles={["reviewer", "admin"]}><p>Desk</p></RequireRole>, { route: "/review", fetchImpl });
    expect(await screen.findByText("This area is for other roles")).toBeInTheDocument();
    expect(screen.queryByText("Desk")).not.toBeInTheDocument();
  });

  it("sign-in needs an email and a password before anything is sent", async () => {
    const { fetchImpl, calls } = fakeBackend({});
    renderApp(<SignIn />, { route: "/signin", path: "/signin", fetchImpl });
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your email.")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/v1/auth/login")).toBe(false);
  });

  it("shows the server's sign-in error and request reference", async () => {
    const { fetchImpl } = fakeBackend({ "POST /api/v1/auth/login": fail(401, "INVALID_CREDENTIALS") });
    renderApp(<SignIn />, { route: "/signin", path: "/signin", fetchImpl });
    await userEvent.type(screen.getByLabelText("Email"), "a@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("The email or password is incorrect.")).toBeInTheDocument();
    expect(screen.getByText("req-test-1")).toBeInTheDocument();
  });

  it("the header strip shows test-mode labels from the server", async () => {
    const { fetchImpl } = fakeBackend({ "GET /api/v1/campaigns": ok([]) });
    renderApp(<Layout />, { route: "/", fetchImpl });
    expect(await screen.findByTestId("mode-paypal")).toHaveTextContent("PayPal test mode, no real money");
    expect(screen.getByTestId("mode-payouts")).toHaveTextContent("Payouts simulated, no money is sent");
    expect(screen.getByTestId("mode-sms")).toHaveTextContent("Simulated SMS, nothing is sent to phones");
  });
});
