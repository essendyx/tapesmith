import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { TableScroll } from '../TableScroll';

describe('TableScroll', () => {
  it('ist ein benannter, per Tab erreichbarer Bereich um die Tabelle', async () => {
    const { container } = render(
      <main>
        <TableScroll label="Rollen">
          <table>
            <thead>
              <tr>
                <th>Rolle</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Weiß 12 mm</td>
              </tr>
            </tbody>
          </table>
        </TableScroll>
      </main>,
    );
    const region = screen.getByRole('region', { name: 'Rollen' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region.querySelector('table')).not.toBeNull();
    await expectNoA11yViolations(container);
  });
});
