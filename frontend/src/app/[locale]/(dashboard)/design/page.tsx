import { redirect } from "next/navigation";

/** Course design now lives in the Course Designer (/outline). */
export default function DesignRedirect() {
  redirect("/outline");
}
