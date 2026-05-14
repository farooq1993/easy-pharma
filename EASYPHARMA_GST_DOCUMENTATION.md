# GST Compliance Module Documentation

## Overview
This GST (Goods and Services Tax) Compliance module helps retail pharmacies in India manage their GST filings under both Regular and Composition schemes.

## Features

### GST Schemes Supported
1. **Regular Scheme**
   - For businesses with unlimited turnover
   - Forms: GSTR-1, GSTR-3B, GSTR-9
   - Monthly filing
   - Input Tax Credit (ITC) allowed
   - B2B supplies allowed

2. **Composition Scheme**
   - For businesses with turnover up to ₹40 Lakhs
   - Forms: CMP-08, GSTR-4
   - Quarterly filing (CMP-08)
   - 1% tax rate for pharmacies
   - No ITC allowed
   - Limited business operations

### Key Components

#### 1. GST Configuration
- Setup GST scheme (Regular/Composition)
- Store GST Number
- Configure filing frequency
- Set legal and trade names

#### 2. GST Filing Management
- Create and track GST filings
- Support for all 5 GST forms (GSTR-1, GSTR-3B, GSTR-9, CMP-08, GSTR-4)
- Track filing status (Draft, Prepared, Filed, Accepted, Rejected)
- Store acknowledgement and reference numbers
- Record filing dates

#### 3. Return Details Tracking
- **Regular Returns**: Detailed tax breakdown by rate (5%, 12%, 18%, 28%)
- **Composition Returns**: Simplified tracking with single tax rate
- Supply categorization (Intrastate, Interstate, Exempt, Zero-rated)
- Input Tax Credit tracking (for regular scheme)

#### 4. Deadline Reminders
- Automatic reminder generation
- Due date tracking
- Overdue filing alerts
- Notification system

### Filing Deadlines

| Form | Frequency | Due Date | Applicable To |
|------|-----------|----------|---------------|
| GSTR-1 | Monthly | 11th of next month | Regular Scheme |
| GSTR-3B | Monthly | 20th of next month | Regular Scheme |
| GSTR-9 | Annual | 31st December | Regular Scheme |
| CMP-08 | Quarterly | 18th of next month | Composition Scheme |
| GSTR-4 | Annual | 31st December | Composition Scheme |

### Tax Rates by Composition Scheme
- **Regular Pharmacy**: Standard GST rates (5%, 12%, 18%, 28%)
- **Composition Pharmacy**: 1% simplified tax rate

## Database Models

### GSTConfiguration
Stores GST setup for each pharmacy/tenant
- Scheme type
- GST number
- Legal and trade names
- Filing frequency
- Turnover limits

### GSTFiling
Main filing record
- Form type (GSTR-1, GSTR-3B, etc.)
- Filing period (start and end dates)
- Due date
- Status tracking
- Acknowledgement numbers
- Penalty/Interest tracking

### GSTReturn
Detailed return information for regular scheme
- Tax breakdowns by rate
- Supply categorization
- Input tax credit details
- Reverse charge details

### GSTCompositionReturn
Simplified return for composition scheme
- Total turnover
- Tax rate and liability
- Supply categorization

### GSTReminder
Filing deadline reminders
- Reminder type
- Reminder date
- Notification status

## Using the GST Module

### Step 1: Configure GST
1. Go to GST Compliance → Configuration
2. Select your scheme (Regular or Composition)
3. Enter GST number (format: 2 digits, 5 letters, 4 digits, 1 letter, 1 alphanumeric, Z, 1 alphanumeric)
4. Enter legal name and optional trade name
5. Set filing frequency
6. Save configuration

### Step 2: Create GST Filing
1. Go to GST Compliance → Filings
2. Click "New Filing"
3. Select form type (GSTR-1, GSTR-3B, etc.)
4. Enter filing period (start and end dates)
5. Confirm due date
6. Save filing

### Step 3: Enter Return Details
1. Open the filing
2. Click "Return Details"
3. Enter supply and tax information
4. For regular scheme: Enter tax amounts by rate (5%, 12%, 18%, 28%)
5. For composition scheme: Enter total turnover and tax liability
6. Save return details

### Step 4: File the Return
1. Open the filing
2. Click "Mark as Filed"
3. Enter acknowledgement number
4. Enter reference number (optional)
5. Confirm filing

### Step 5: Track Reminders
1. Go to GST Compliance → Reminders
2. View all upcoming and overdue filings
3. Take action on pending reminders

## API Endpoints

### GET /gst/
- Dashboard view with filing overview

### GET /gst/config/
- GST configuration page

### GET /gst/filings/
- List all filings

### GET /gst/filings/<id>/
- View filing details

### POST /gst/filings/add/
- Create new filing

### POST /gst/filings/<id>/edit/
- Update filing

### POST /gst/api/
- API for marking filed, accepting, creating reminders

## Important Notes for Pharmacies

### Regular Scheme Requirements
- Maintain detailed records of all supplies
- File GSTR-1 by 11th of next month
- File GSTR-3B by 20th of next month
- Claim Input Tax Credit (ITC) quarterly
- File annual return GSTR-9 by 31st December
- Can make B2B supplies
- Can export goods

### Composition Scheme Restrictions
- Can only make B2C (retail) supplies
- Cannot issue tax invoice, must issue Bill
- No ITC allowed (cannot recover input tax)
- Tax rate: 1% for pharmacies
- File quarterly return (CMP-08) by 18th
- File annual return (GSTR-4) by 31st December
- Limited to ₹40 Lakhs turnover (including services)
- Cannot make inter-state supplies beyond ₹20 Lakhs

### Penalties and Interest
- Late filing: ₹100-₹500 per day (Regular), ₹500-₹1,000 per day (Composition)
- Interest: 18% per annum on unpaid tax
- Record all penalties and interest in the system

## Compliance Checklist

### Monthly (Regular Scheme)
- [ ] Reconcile sales with invoices
- [ ] Calculate tax amounts
- [ ] File GSTR-1 by 11th
- [ ] Review GST paid/received
- [ ] File GSTR-3B by 20th

### Quarterly (Composition Scheme)
- [ ] Reconcile sales
- [ ] Calculate quarterly turnover
- [ ] File CMP-08 by 18th
- [ ] Review tax paid

### Annual (Both Schemes)
- [ ] Prepare detailed records
- [ ] Reconcile with purchase/sales books
- [ ] Calculate annual GST liability
- [ ] File GSTR-9 or GSTR-4 by 31st December
- [ ] Claim any refunds due

## Troubleshooting

### Common Issues

1. **Filing Rejected**: Review return details, ensure all amounts match GST portal, check for any discrepancies

2. **Missing Reminders**: Create reminders manually through the API or system

3. **Deadline Calculation Error**: Verify filing frequency setting, confirm period dates

4. **Access Issues**: Ensure user is authenticated and associated with correct tenant/pharmacy

## Support and Updates

For GST law updates and amendments, refer to:
- GST India Portal: https://www.gst.gov.in/
- CBIC Circulars: https://www.cbic.gov.in/
- Trade associations: IAMAI, Pharmacy councils

## Future Enhancements

- Auto-calculation of GST amounts from invoices
- Auto-filing integration with GST portal
- SMS/Email notifications
- Multi-state tracking
- Export to GST portal format
- Advanced analytics and reports
