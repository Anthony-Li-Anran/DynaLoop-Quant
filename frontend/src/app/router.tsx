import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { path: "research", lazy: () => import("../pages/ResearchPage").then((module) => ({ Component: module.ResearchPage })) },
      { path: "evidence", lazy: () => import("../pages/EvidencePage").then((module) => ({ Component: module.EvidencePage })) },
      { path: "subjective", lazy: () => import("../pages/SubjectivePage").then((module) => ({ Component: module.SubjectivePage })) },
      { path: "decision", lazy: () => import("../pages/DecisionPage").then((module) => ({ Component: module.DecisionPage })) },
      { path: "components", lazy: () => import("../pages/ComponentsPage").then((module) => ({ Component: module.ComponentsPage })) },
      { index: true, lazy: () => import("../pages/OverviewPage").then((module) => ({ Component: module.OverviewPage })) },
      { path: "data", lazy: () => import("../pages/DataPage").then((module) => ({ Component: module.DataPage })) },
      { path: "data/datasets/:datasetId/preview", lazy: () => import("../pages/DatasetPreviewPage").then((module) => ({ Component: module.DatasetPreviewPage })) },
      { path: "backtests", lazy: () => import("../pages/BacktestsPage").then((module) => ({ Component: module.BacktestsPage })) },
      { path: "experiments", lazy: () => import("../pages/ExperimentsPage").then((module) => ({ Component: module.ExperimentsPage })) },
      { path: "loop", lazy: () => import("../pages/LoopPage").then((module) => ({ Component: module.LoopPage })) },
      { path: "runtime", lazy: () => import("../pages/RuntimePage").then((module) => ({ Component: module.RuntimePage })) },
      { path: "settings", lazy: () => import("../pages/SettingsPage").then((module) => ({ Component: module.SettingsPage })) },
    ],
  },
]);
