import { redirect } from "next/navigation";

/** Slide review now lives in the Material Designer (/studio). */
export default function SlidesRedirect() {
  redirect("/studio");
}
