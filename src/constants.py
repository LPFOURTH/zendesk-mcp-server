US_TEMPLATE_HEADER = """<h2 class="first:mt-1.5">What's New?</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Use the links below to find out more about each item release for
    <a href="#h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</a>,
    <a href="#h_01JQXYFHC8R57QW1SDFY29RW86">Platform</a>, and
    <a href="#h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</a>
  </span>
</p>

<p>
  <span class="wysiwyg-font-size-medium"><strong>Release date:</strong> DD Month name YYYY</span>
</p>

<p>&nbsp;</p>

<h2 id="h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</h2>
<p>&nbsp;</p>

<h2 id="h_01JQXYFHC8R57QW1SDFY29RW86">Platform</h2>
<p>&nbsp;</p>
<h2 id="h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</h2>
<p>A list of defect/bug fixes</p>
<p>&nbsp;</p>
<h2>All features - move them to the right place</h2>
"""

US_TEMPLATE_MIDDLE = """
<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
"""

TEMPLATE_FEATURE_DETAILS_FOOTER = """
<ul>
  <li><span class="wysiwyg-font-size-medium">Enabled by default? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Set up by customer admin? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Enable via support ticket? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Affects configuration or data? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Roles affected: If applicable</span></li>
</ul>

<h2>Instructions/Screenshots</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Description and instructions for enabling (if applicable) and using the new/changed functionality. If there's a large amount of information, include headers (which can be turned into a table of contents if required).
  </span>
</p>

<p>&nbsp;</p>
"""

UK_TEMPLATE_HEADER = """
<h2 class="first:mt-1.5">What's New?</h2>
"""

UK_TEMPLATE_MIDDLE = """
<p>
  <span class="wysiwyg-font-size-medium">
    Use the links above to find out more about this release.
  </span>
</p>
<p>
  <span class="wysiwyg-font-size-medium">
    <strong>Release date:</strong> DD Month name YYYY
  </span>
</p>
<p>&nbsp;</p>

<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
"""

ENVIRONMENTS = {
    "prod": {
        "base_url": "https://hotschedules.zendesk.com",
        "section_id": 5404916050957,
        "permission_group_id": 1721132,
        "user_segment_id": 171472,
        "author_id": 397321102531,
    },
    "dev": {
        "base_url": "https://hotschedules1626093811.zendesk.com",
        "section_id": 34086316530573,
        "permission_group_id": 4407361031693,
        "user_segment_id": None,
        "author_id": 420190638631,
    },
}
