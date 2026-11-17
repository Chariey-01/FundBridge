import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, ErrorNotice, Field, Notice } from "../components/ui.tsx";
import { useSession } from "../session/SessionContext.tsx";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function Register() {
  const { client, signIn } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState(false);

  const errors = {
    email: !EMAIL.test(email.trim()) ? "Enter a valid email address." : null,
    password: password.length < 12 ? "Use at least 12 characters." : null,
    confirm: confirm !== password ? "The passwords do not match." : null,
  };
  const valid = !errors.email && !errors.password && !errors.confirm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (!valid) return;
    setBusy(true); setError(null);
    try {
      await client.register(email.trim(), password); // 201 with {id, role}; registration never returns a token
      setCreated(true);
      try {
        await signIn(email.trim(), password);
        navigate("/campaigns", { replace: true });
      } catch {
        navigate("/signin", { replace: true, state: { email: email.trim() } });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container section" style={{ maxWidth: 520 }}>
      <form className="card form" onSubmit={submit} noValidate aria-labelledby="register-title">
        <h1 id="register-title" style={{ fontSize: "1.9rem" }}>Create an account</h1>
        <p className="muted" style={{ margin: 0 }}>New accounts can donate. Creator, beneficiary and staff roles are assigned by an administrator.</p>
        <Field label="Email" htmlFor="reg-email" error={touched ? errors.email : null}>
          <input id="reg-email" className="input" type="email" autoComplete="email" value={email} aria-invalid={touched && !!errors.email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="reg-password" help={`${password.length}/12 characters minimum`} error={touched ? errors.password : null}>
          <input id="reg-password" className="input" type="password" autoComplete="new-password" value={password} aria-invalid={touched && !!errors.password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm password" htmlFor="reg-confirm" error={touched ? errors.confirm : null}>
          <input id="reg-confirm" className="input" type="password" autoComplete="new-password" value={confirm} aria-invalid={touched && !!errors.confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        {created && <Notice tone="success" title="Account created">Signing you in…</Notice>}
        {error != null && <ErrorNotice error={error} />}
        <Button type="submit" block busy={busy} busyLabel="Creating account">Create account</Button>
        <p className="small muted" style={{ margin: 0 }}>Already registered? <Link to="/signin">Sign in</Link>.</p>
      </form>
    </div>
  );
}
