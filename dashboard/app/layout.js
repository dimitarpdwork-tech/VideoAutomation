import './globals.css';
import './insights.css';
import './channels.css';
import './review.css';
export const metadata = {title: 'Story Shorts Studio', description: 'Make, review and schedule story videos'};
export default function Layout({children}) {
  return <html lang="en"><body>{children}</body></html>;
}
