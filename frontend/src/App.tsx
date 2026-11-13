import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout.tsx";
import { RequireRole } from "./components/RequireRole.tsx";
import { AdminPeople } from "./pages/AdminPeople.tsx";
import { BeneficiaryDashboard } from "./pages/BeneficiaryDashboard.tsx";
import { Browse } from "./pages/Browse.tsx";
import { CampaignDetail } from "./pages/CampaignDetail.tsx";
import { CampaignEdit } from "./pages/CampaignEdit.tsx";
import { CampaignNew } from "./pages/CampaignNew.tsx";
import { CreatorDashboard } from "./pages/CreatorDashboard.tsx";
import { DonationDetail } from "./pages/DonationDetail.tsx";
import { DonationReturn } from "./pages/DonationReturn.tsx";
import { Home } from "./pages/Home.tsx";
import { MyDonations } from "./pages/MyDonations.tsx";
import { NotFound } from "./pages/NotFound.tsx";
import { Onboard } from "./pages/Onboard.tsx";
import { Register } from "./pages/Register.tsx";
import { ReviewDesk } from "./pages/ReviewDesk.tsx";
import { SignIn } from "./pages/SignIn.tsx";
import { SystemModes } from "./pages/SystemModes.tsx";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="campaigns" element={<Browse />} />
        <Route path="campaigns/:id" element={<CampaignDetail />} />
        <Route path="system" element={<SystemModes />} />
        <Route path="signin" element={<SignIn />} />
        <Route path="register" element={<Register />} />
        <Route path="donate/return" element={<RequireRole><DonationReturn /></RequireRole>} />
        <Route path="donations/:id" element={<RequireRole><DonationDetail /></RequireRole>} />
        <Route path="account/donations" element={<RequireRole><MyDonations /></RequireRole>} />
        <Route path="creator" element={<RequireRole roles={["creator", "admin"]}><CreatorDashboard /></RequireRole>} />
        <Route path="creator/new" element={<RequireRole roles={["creator", "admin"]}><CampaignNew /></RequireRole>} />
        <Route path="creator/campaigns/:id" element={<RequireRole roles={["creator", "admin"]}><CampaignEdit /></RequireRole>} />
        <Route path="beneficiary" element={<RequireRole roles={["beneficiary"]}><BeneficiaryDashboard /></RequireRole>} />
        <Route path="review" element={<RequireRole roles={["reviewer", "admin"]}><ReviewDesk /></RequireRole>} />
        <Route path="agent/onboard" element={<RequireRole roles={["agent", "admin"]}><Onboard /></RequireRole>} />
        <Route path="admin/people" element={<RequireRole roles={["admin"]}><AdminPeople /></RequireRole>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
