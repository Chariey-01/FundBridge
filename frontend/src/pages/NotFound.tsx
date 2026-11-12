import { Link } from "react-router-dom";
import { Empty } from "../components/ui.tsx";

export function NotFound() {
  return (
    <div className="container section">
      <Empty title="Page not found"><p><Link to="/">Go to the home page</Link></p></Empty>
    </div>
  );
}
