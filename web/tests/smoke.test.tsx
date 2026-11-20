import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import Page from "../app/page";

it("renders the scaffold title", () => {
  render(<Page />);
  expect(screen.getByRole("heading", { name: "Beauty Ad Creative Agents" })).toBeTruthy();
});
